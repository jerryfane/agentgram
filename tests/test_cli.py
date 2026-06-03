from __future__ import annotations

import argparse
import io
import json
import stat
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentgram_tg import cli
from agentgram_tg.telegram import TelegramClient, TelegramError, encode_multipart_form, redact_token


def has_writable_tempdir() -> bool:
    try:
        with tempfile.TemporaryDirectory():
            return True
    except OSError:
        return False


class CliPayloadTests(unittest.TestCase):
    def test_build_send_payload_uses_json_telegram_fields(self) -> None:
        payload = cli.build_send_payload(
            chat_id="12345",
            text="hello",
            parse_mode="HTML",
            silent=True,
            no_preview=True,
        )

        self.assertEqual(
            payload,
            {
                "chat_id": "12345",
                "text": "hello",
                "parse_mode": "HTML",
                "disable_notification": True,
                "link_preview_options": {"is_disabled": True},
            },
        )

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.normalize_text(["   "])

    def test_long_text_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.validate_text("x" * (cli.MAX_TEXT_LENGTH + 1), parse_mode=None)

    def test_split_message_text_keeps_chunks_under_limit(self) -> None:
        text = "alpha beta gamma delta epsilon"

        chunks = cli.split_message_text(text, limit=16)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunk.split("] ", 1)[1] for chunk in chunks), text)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 16)
        self.assertTrue(chunks[0].startswith("[1/"))

    def test_split_message_text_prefers_paragraph_boundaries(self) -> None:
        text = "first paragraph\n\nsecond paragraph\nthird paragraph"

        chunks = cli.split_message_text(text, limit=28)

        self.assertIn("first paragraph\n\n", chunks[0])
        self.assertEqual("".join(chunk.split("] ", 1)[1] for chunk in chunks), text)

    def test_split_message_text_splits_mid_word_as_last_resort(self) -> None:
        chunks = cli.split_message_text("abcdefghij", limit=10)

        self.assertEqual(chunks, ["[1/3] abcd", "[2/3] efgh", "[3/3] ij"])

    def test_validate_text_filename_rejects_paths(self) -> None:
        self.assertEqual(cli.validate_text_filename(None), "agentgram-message.txt")
        self.assertEqual(cli.validate_text_filename("report.md"), "report.md")
        with self.assertRaisesRegex(cli.CliError, "not a path"):
            cli.validate_text_filename("../report.md")
        with self.assertRaisesRegex(cli.CliError, "not a path"):
            cli.validate_text_filename("nested\\report.md")

    def test_html_length_uses_visible_text(self) -> None:
        payload = cli.build_send_payload(
            chat_id="12345",
            text=f"<b>{'x' * cli.MAX_TEXT_LENGTH}</b>",
            parse_mode="HTML",
            silent=False,
            no_preview=False,
        )

        self.assertEqual(payload["text"], f"<b>{'x' * cli.MAX_TEXT_LENGTH}</b>")

    def test_html_visible_text_over_limit_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.build_send_payload(
                chat_id="12345",
                text=f"<b>{'x' * (cli.MAX_TEXT_LENGTH + 1)}</b>",
                parse_mode="HTML",
                silent=False,
                no_preview=False,
            )

    def test_markdown_code_length_uses_visible_text(self) -> None:
        payload = cli.build_send_payload(
            chat_id="12345",
            text=f"`{'.' * cli.MAX_TEXT_LENGTH}`",
            parse_mode="MarkdownV2",
            silent=False,
            no_preview=False,
        )

        self.assertEqual(payload["text"], f"`{'.' * cli.MAX_TEXT_LENGTH}`")

    def test_markdown_code_over_limit_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.build_send_payload(
                chat_id="12345",
                text=f"`{'.' * (cli.MAX_TEXT_LENGTH + 1)}`",
                parse_mode="MarkdownV2",
                silent=False,
                no_preview=False,
            )

    def test_markdown_link_destination_is_not_visible_text(self) -> None:
        payload = cli.build_send_payload(
            chat_id="12345",
            text=f"[{'x' * cli.MAX_TEXT_LENGTH}](https://example.com/{'y' * 5000})",
            parse_mode="MarkdownV2",
            silent=False,
            no_preview=False,
        )

        self.assertTrue(payload["text"].startswith("["))

    def test_markdown_link_label_over_limit_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.build_send_payload(
                chat_id="12345",
                text=f"[{'x' * (cli.MAX_TEXT_LENGTH + 1)}](https://example.com)",
                parse_mode="MarkdownV2",
                silent=False,
                no_preview=False,
            )

    def test_build_document_payload_uses_telegram_fields(self) -> None:
        payload = cli.build_document_payload(
            chat_id="12345",
            caption="report",
            parse_mode="HTML",
            silent=True,
        )

        self.assertEqual(
            payload,
            {
                "chat_id": "12345",
                "caption": "report",
                "parse_mode": "HTML",
                "disable_notification": True,
            },
        )

    def test_build_document_payload_allows_no_caption(self) -> None:
        payload = cli.build_document_payload(
            chat_id="12345",
            caption=None,
            parse_mode=None,
            silent=False,
        )

        self.assertEqual(payload, {"chat_id": "12345"})

    def test_document_payload_requires_chat_id(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.build_document_payload(chat_id="", caption=None, parse_mode=None, silent=False)

    def test_caption_length_uses_visible_html(self) -> None:
        cli.validate_caption(f"<b>{'x' * cli.MAX_CAPTION_LENGTH}</b>", parse_mode="HTML")

    def test_plain_caption_over_limit_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.validate_caption("x" * (cli.MAX_CAPTION_LENGTH + 1), parse_mode=None)

    def test_caption_visible_text_over_limit_is_rejected(self) -> None:
        with self.assertRaises(cli.CliError):
            cli.validate_caption(f"<b>{'x' * (cli.MAX_CAPTION_LENGTH + 1)}</b>", parse_mode="HTML")

    def test_caption_markdown_link_destination_is_not_visible_text(self) -> None:
        cli.validate_caption(
            f"[{'x' * cli.MAX_CAPTION_LENGTH}](https://example.com/{'y' * 5000})",
            parse_mode="MarkdownV2",
        )

    def test_document_path_validation_accepts_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("hello\n", encoding="utf-8")

            self.assertEqual(cli.validate_document_path(path), path)

    def test_document_path_validation_rejects_missing_file(self) -> None:
        with self.assertRaisesRegex(cli.CliError, "file does not exist"):
            cli.validate_document_path("/tmp/agentgram-missing-file")

    def test_document_path_validation_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(cli.CliError, "not a regular file"):
                cli.validate_document_path(tmp)

    def test_document_path_validation_rejects_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.txt"
            path.touch()

            with self.assertRaisesRegex(cli.CliError, "file is empty"):
                cli.validate_document_path(path)

    def test_document_path_validation_rejects_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.txt"
            with path.open("wb") as handle:
                handle.truncate(cli.MAX_DOCUMENT_BYTES + 1)

            with self.assertRaisesRegex(cli.CliError, "file is too large"):
                cli.validate_document_path(path)

    def test_document_path_validation_rejects_unreadable_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.txt"
            path.write_text("secret\n", encoding="utf-8")
            with mock.patch("pathlib.Path.open", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(cli.CliError, "not readable"):
                    cli.validate_document_path(path)

    def test_extract_chat_candidates_deduplicates_chats(self) -> None:
        updates = [
            {"message": {"chat": {"id": 10, "type": "private", "first_name": "Ada"}}},
            {"edited_message": {"chat": {"id": 10, "type": "private", "first_name": "Ada"}}},
            {"channel_post": {"chat": {"id": -100, "type": "channel", "title": "Ops"}}},
        ]

        self.assertEqual(
            cli.extract_chat_candidates(updates),
            [
                {"id": "10", "type": "private", "title": "", "username": "", "name": "Ada"},
                {"id": "-100", "type": "channel", "title": "Ops", "username": "", "name": "Ops"},
            ],
        )


class InboxTests(unittest.TestCase):
    def test_inbox_help_lists_options(self) -> None:
        inbox_parser = cli.build_parser()._subparsers._group_actions[0].choices["inbox"]
        output = inbox_parser.format_help()

        for option in (
            "--chat-id",
            "--limit",
            "--since",
            "--forwarded-only",
            "--include-plain",
            "--peek",
            "--ack",
            "--format",
            "--output",
            "--download-files",
            "--download-dir",
            "--max-file-bytes",
            "markdown",
            "compact",
            "json",
            "jsonl",
        ):
            self.assertIn(option, output)

    def test_parse_duration_accepts_minutes_hours_and_days(self) -> None:
        self.assertEqual(cli.parse_duration("15m"), 900)
        self.assertEqual(cli.parse_duration("3h"), 10800)
        self.assertEqual(cli.parse_duration("1d"), 86400)

    def test_parse_duration_rejects_invalid_value(self) -> None:
        with self.assertRaisesRegex(cli.CliError, "since must be a duration"):
            cli.parse_duration("three hours")

    def test_default_inbox_fetches_forwarded_messages_as_markdown(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(3, 30, 1_700_000_030, text="newest", origin=self.origin_hidden_user("Hidden Ada", date=1_700_000_030)),
                self.update(1, 10, 1_700_000_010, text="oldest", origin=self.origin_user("Grace", date=1_700_000_010)),
                self.update(2, 20, 1_700_000_020, text="plain", origin=None),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_040):
                code = cli.run(
                    ["inbox"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        client_cls.return_value.get_updates.assert_called_once_with(
            100,
            timeout=0,
            allowed_updates=["message"],
        )
        output = stdout.getvalue()
        self.assertIn("# Agentgram Inbox", output)
        self.assertLess(output.find("oldest"), output.find("newest"))
        self.assertIn("Original source: Grace", output)
        self.assertIn("Original sent at: 2023-11-14T22:13:30Z", output)
        self.assertIn("Forwarded received at: 2023-11-14T22:13:30Z", output)
        self.assertIn("Hidden Ada (privacy-hidden user)", output)
        self.assertNotIn("plain", output)

    def test_inbox_uses_chat_id_override(self) -> None:
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(1, 10, 1_700_000_000, chat_id=123, text="included", origin=self.origin_user("Ada")),
                self.update(2, 20, 1_700_000_000, chat_id=99, text="excluded", origin=self.origin_user("Grace")),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                stdout = io.StringIO()
                code = cli.run(
                    ["inbox", "--chat-id", "123"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertIn("included", stdout.getvalue())
        self.assertNotIn("excluded", stdout.getvalue())

    def test_include_plain_includes_direct_messages(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(1, 10, 1_700_000_000, text="plain note", origin=None),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--include-plain"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertIn("direct message to bot", stdout.getvalue())
        self.assertIn("plain note", stdout.getvalue())

    def test_since_filters_old_messages(self) -> None:
        updates = [
            self.update(1, 10, 1_700_000_000, text="too old", origin=self.origin_user("Ada")),
            self.update(2, 20, 1_700_000_090, text="recent", origin=self.origin_user("Ada")),
        ]

        records = cli.inbox_records(
            updates,
            chat_id="99",
            since_seconds=60,
            include_plain=False,
            now=1_700_000_100,
        )

        self.assertEqual([record["content"] for record in records], ["recent"])

    def test_json_output_emits_stable_records(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(
                    1,
                    10,
                    1_700_000_000,
                    text="hello",
                    origin=self.origin_user("Ada", username="ada", date=1_699_999_990),
                ),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--format", "json"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["content"], "hello")
        self.assertEqual(payload[0]["origin"]["type"], "user")
        self.assertEqual(payload[0]["origin"]["source"], "Ada (@ada)")
        self.assertEqual(payload[0]["date_iso"], "2023-11-14T22:13:20Z")
        self.assertEqual(payload[0]["original_date"], 1_699_999_990)
        self.assertEqual(payload[0]["original_date_iso"], "2023-11-14T22:13:10Z")
        self.assertEqual(payload[0]["received_index"], 1)

    def test_inbox_orders_forwarded_records_by_original_time(self) -> None:
        updates = [
            self.update(1, 10, 1_700_000_030, text="third received first", origin=self.origin_user("Ada", date=1_700_000_003)),
            self.update(2, 20, 1_700_000_010, text="first received second", origin=self.origin_user("Ada", date=1_700_000_001)),
            self.update(3, 30, 1_700_000_020, text="second received third", origin=self.origin_user("Ada", date=1_700_000_002)),
        ]

        records = cli.inbox_records(
            updates,
            chat_id="99",
            since_seconds=60,
            include_plain=False,
            now=1_700_000_040,
        )

        self.assertEqual(
            [record["content"] for record in records],
            ["first received second", "second received third", "third received first"],
        )

    def test_inbox_original_time_ties_keep_received_order(self) -> None:
        updates = [
            self.update(1, 10, 1_700_000_010, text="first", origin=self.origin_user("Ada", date=1_700_000_000)),
            self.update(2, 20, 1_700_000_011, text="second", origin=self.origin_user("Ada", date=1_700_000_000)),
        ]

        records = cli.inbox_records(
            updates,
            chat_id="99",
            since_seconds=60,
            include_plain=False,
            now=1_700_000_040,
        )

        self.assertEqual([record["content"] for record in records], ["first", "second"])
        self.assertEqual([record["received_index"] for record in records], [1, 2])

    def test_include_plain_preserves_chronological_position(self) -> None:
        updates = [
            self.update(1, 10, 1_700_000_010, text="forwarded first", origin=self.origin_user("Ada", date=1_700_000_010)),
            self.update(2, 20, 1_700_000_020, text="plain middle", origin=None),
            self.update(3, 30, 1_700_000_030, text="forwarded last", origin=self.origin_user("Ada", date=1_700_000_030)),
        ]

        records = cli.inbox_records(
            updates,
            chat_id="99",
            since_seconds=60,
            include_plain=True,
            now=1_700_000_040,
        )

        self.assertEqual([record["content"] for record in records], ["forwarded first", "plain middle", "forwarded last"])

    def test_compact_output_emits_line_oriented_context(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(
                    1,
                    10,
                    1_700_000_000,
                    text="hello\n\nworld",
                    origin=self.origin_user("Ada", username="ada", date=1_699_999_990),
                ),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--format", "compact"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue().strip(),
            "1. [2023-11-14T22:13:10Z] Ada (@ada): hello world",
        )

    def test_compact_output_includes_downloaded_attachment_context(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_updates.return_value = [
                    self.update(
                        1,
                        10,
                        1_700_000_000,
                        text="",
                        origin=self.origin_user("Ada", username="ada"),
                        media={
                            "caption": "caption text",
                            "document": {"file_id": "secret-file-id", "file_name": "report.txt", "file_size": 5},
                        },
                    ),
                ]
                client.get_file.return_value = {
                    "file_id": "secret-file-id",
                    "file_path": "documents/report.txt",
                    "file_size": 5,
                }
                client.download_file.return_value = {
                    "path": str(target),
                    "bytes": 5,
                    "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--include-plain", "--download-files", "--download-dir", tmp, "--format", "compact"],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn(f"caption text | attachments: document report.txt 5 bytes -> {target}", output)
        self.assertNotIn("secret-file-id", output)

    def test_jsonl_output_emits_one_record_per_line(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(1, 10, 1_700_000_000, text="first", origin=self.origin_user("Ada")),
                self.update(2, 20, 1_700_000_001, text="second", origin=self.origin_user("Grace")),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_002):
                code = cli.run(
                    ["inbox", "--format", "jsonl"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        lines = stdout.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["content"], "first")
        self.assertEqual(json.loads(lines[1])["content"], "second")

    def test_jsonl_empty_output_emits_no_blank_stdout_line(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = []
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_002):
                code = cli.run(
                    ["inbox", "--format", "jsonl"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")

    def test_forward_origin_rendering_covers_chat_and_channel(self) -> None:
        chat = cli.render_forward_origin(
            {
                "type": "chat",
                "sender_chat": {"id": -10, "type": "supergroup", "title": "Ops"},
                "author_signature": "Moderator",
            }
        )
        channel = cli.render_forward_origin(
            {
                "type": "channel",
                "chat": {"id": -100, "type": "channel", "title": "Deploys"},
                "message_id": 777,
                "author_signature": "Release Bot",
            }
        )

        self.assertEqual(chat["type"], "chat")
        self.assertIn("Ops", chat["source"])
        self.assertIn("signature: Moderator", chat["source"])
        self.assertEqual(channel["type"], "channel")
        self.assertIn("Deploys", channel["source"])
        self.assertIn("original message_id: 777", channel["source"])
        self.assertIn("signature: Release Bot", channel["source"])

    def test_extract_message_content_uses_caption_and_media_summary(self) -> None:
        self.assertEqual(cli.extract_message_content({"caption": "image caption"}), "image caption")
        self.assertEqual(
            cli.extract_message_content({"document": {"file_name": "report.pdf", "mime_type": "application/pdf"}}),
            "[document: report.pdf]",
        )
        self.assertEqual(cli.extract_message_content({"photo": [{}, {}]}), "[photo: 2 sizes]")
        self.assertEqual(cli.extract_message_content({}), "[message without text]")

    def test_inbox_json_includes_document_attachment_metadata(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(
                    1,
                    10,
                    1_700_000_000,
                    text="",
                    origin=self.origin_user("Ada"),
                    media={
                        "document": {
                            "file_id": "doc-file-id",
                            "file_unique_id": "doc-unique",
                            "file_name": "report.pdf",
                            "mime_type": "application/pdf",
                            "file_size": 123,
                        },
                        "caption": "quarterly report",
                    },
                ),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--format", "json"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        attachment = payload[0]["attachments"][0]
        self.assertEqual(attachment["kind"], "document")
        self.assertEqual(attachment["file_id"], "doc-file-id")
        self.assertEqual(attachment["file_name"], "report.pdf")
        self.assertEqual(attachment["file_name_source"], "telegram")
        self.assertEqual(attachment["mime_type"], "application/pdf")
        self.assertEqual(attachment["file_size"], 123)
        self.assertEqual(attachment["caption"], "quarterly report")

    def test_extract_message_attachments_covers_supported_media(self) -> None:
        message = {
            "message_id": 42,
            "caption": "media batch",
            "document": {"file_id": "document-id", "file_unique_id": "document-u", "file_name": "doc.txt"},
            "audio": {"file_id": "audio-id", "file_unique_id": "audio-u", "title": "song"},
            "video": {"file_id": "video-id", "file_unique_id": "video-u", "mime_type": "video/mp4"},
            "animation": {"file_id": "animation-id", "file_unique_id": "animation-u"},
            "voice": {"file_id": "voice-id", "file_unique_id": "voice-u"},
            "video_note": {"file_id": "video-note-id", "file_unique_id": "video-note-u"},
            "photo": [
                {"file_id": "small-photo-id", "file_unique_id": "small-photo-u", "width": 10, "height": 10},
                {
                    "file_id": "large-photo-id",
                    "file_unique_id": "large-photo-u",
                    "width": 100,
                    "height": 100,
                    "file_size": 200,
                },
            ],
        }

        attachments = cli.extract_message_attachments(message)

        self.assertEqual(
            [attachment["kind"] for attachment in attachments],
            ["document", "audio", "video", "animation", "voice", "video_note", "photo"],
        )
        self.assertEqual(attachments[-1]["file_id"], "large-photo-id")
        self.assertTrue(attachments[2]["file_name"].endswith(".mp4"))
        self.assertEqual({attachment["caption"] for attachment in attachments}, {"media batch"})

    def test_telegram_metadata_filename_slashes_are_sanitized_for_inbox(self) -> None:
        attachments = cli.extract_message_attachments(
            {
                "message_id": 42,
                "audio": {"file_id": "audio-id", "file_unique_id": "audio-u", "title": "AC/DC"},
                "document": {"file_id": "doc-id", "file_unique_id": "doc-u", "file_name": "../report.txt"},
            }
        )

        by_kind = {attachment["kind"]: attachment for attachment in attachments}
        self.assertEqual(by_kind["audio"]["file_name"], "AC_DC")
        self.assertEqual(by_kind["document"]["file_name"], "_report.txt")

    def test_inbox_markdown_hides_raw_file_ids_without_downloads(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(
                    1,
                    10,
                    1_700_000_000,
                    text="",
                    origin=self.origin_user("Ada"),
                    media={"document": {"file_id": "secret-file-id", "file_name": "report.pdf", "file_size": 12}},
                ),
                self.update(
                    2,
                    11,
                    1_700_000_000,
                    text="",
                    origin=self.origin_user("Ada"),
                    media={"photo": [{"file_id": "raw-photo-file-id", "width": 100, "height": 100}]},
                ),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("document report.pdf 12 bytes", output)
        self.assertNotIn("secret-file-id", output)
        self.assertNotIn("raw-photo-file-id", output)
        self.assertIn("photo-11-id-", output)

    def test_inbox_download_files_acknowledges_only_after_download(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_updates.side_effect = [
                    [
                        self.update(
                            1,
                            10,
                            1_700_000_000,
                            text="",
                            origin=None,
                            media={
                                "document": {
                                    "file_id": "doc-file-id",
                                    "file_unique_id": "doc-u",
                                    "file_name": "report.txt",
                                    "file_size": 5,
                                }
                            },
                        )
                    ],
                    [],
                ]
                client.get_file.return_value = {
                    "file_id": "doc-file-id",
                    "file_unique_id": "doc-u",
                    "file_path": "documents/report.txt",
                    "file_size": 5,
                }
                client.download_file.return_value = {
                    "path": str(Path(tmp) / "report.txt"),
                    "bytes": 5,
                    "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--include-plain", "--download-files", "--download-dir", tmp, "--ack"],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 0)
        self.assertEqual(client.get_updates.call_args_list[-1].kwargs["offset"], 2)
        self.assertLess(
            client.method_calls.index(mock.call.download_file("documents/report.txt", Path(tmp) / "report.txt", expected_size=5, max_bytes=cli.MAX_DOWNLOAD_BYTES)),
            client.method_calls.index(mock.call.get_updates(1, offset=2, timeout=0, allowed_updates=["message"])),
        )
        self.assertIn("downloaded files=1", stdout.getvalue())

    def test_inbox_download_files_lists_multiple_attachments(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            first_target = Path(tmp) / "report.txt"
            second_target = Path(tmp) / "photo-10-id-b34c1e9b3ca5ceb9.jpg"
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_updates.return_value = [
                    self.update(
                        1,
                        10,
                        1_700_000_000,
                        text="",
                        origin=None,
                        media={
                            "document": {"file_id": "doc-file-id", "file_name": "report.txt", "file_size": 5},
                            "photo": [{"file_id": "photo-file-id", "width": 100, "height": 100, "file_size": 9}],
                        },
                    )
                ]
                client.get_file.side_effect = [
                    {"file_id": "doc-file-id", "file_path": "documents/report.txt", "file_size": 5},
                    {"file_id": "photo-file-id", "file_path": "photos/photo.jpg", "file_size": 9},
                ]
                client.download_file.side_effect = [
                    {"path": str(first_target), "bytes": 5, "sha256": "first"},
                    {"path": str(second_target), "bytes": 9, "sha256": "second"},
                ]
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--include-plain", "--download-files", "--download-dir", tmp],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 0)
        self.assertEqual(client.get_file.call_count, 2)
        self.assertEqual(client.download_file.call_count, 2)
        self.assertIn("downloaded files=2", stdout.getvalue())
        self.assertIn(f"path={first_target} bytes=5 sha256=first", stdout.getvalue())
        self.assertIn(f"path={second_target} bytes=9 sha256=second", stdout.getvalue())

    def test_inbox_json_download_files_keeps_stdout_parseable(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_updates.return_value = [
                    self.update(
                        1,
                        10,
                        1_700_000_000,
                        text="",
                        origin=None,
                        media={"document": {"file_id": "doc-file-id", "file_name": "report.txt", "file_size": 5}},
                    )
                ]
                client.get_file.return_value = {
                    "file_id": "doc-file-id",
                    "file_path": "documents/report.txt",
                    "file_size": 5,
                }
                client.download_file.return_value = {
                    "path": str(target),
                    "bytes": 5,
                    "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--include-plain", "--download-files", "--download-dir", tmp, "--format", "json"],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["attachments"][0]["download"]["path"], str(target))
        self.assertNotIn("downloaded files=", stdout.getvalue())

    def test_inbox_jsonl_download_files_keeps_stdout_parseable(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_updates.return_value = [
                    self.update(
                        1,
                        10,
                        1_700_000_000,
                        text="",
                        origin=None,
                        media={"document": {"file_id": "doc-file-id", "file_name": "report.txt", "file_size": 5}},
                    )
                ]
                client.get_file.return_value = {
                    "file_id": "doc-file-id",
                    "file_path": "documents/report.txt",
                    "file_size": 5,
                }
                client.download_file.return_value = {
                    "path": str(target),
                    "bytes": 5,
                    "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--include-plain", "--download-files", "--download-dir", tmp, "--format", "jsonl"],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["attachments"][0]["download"]["path"], str(target))

    def test_inbox_download_files_without_attachments_does_not_create_tempdir(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = []
            with mock.patch("agentgram_tg.cli.tempfile.mkdtemp") as mkdtemp:
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--download-files"],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 0)
        mkdtemp.assert_not_called()
        self.assertIn("No inbox messages found.", stdout.getvalue())

    def test_inbox_download_failure_does_not_acknowledge(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_updates.return_value = [
                    self.update(
                        1,
                        10,
                        1_700_000_000,
                        text="",
                        origin=None,
                        media={"document": {"file_id": "doc-file-id", "file_name": "report.txt", "file_size": 5}},
                    )
                ]
                client.get_file.side_effect = TelegramError("Bad Request: file is too big")
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--include-plain", "--download-files", "--download-dir", tmp, "--ack"],
                        stdout=io.StringIO(),
                        stderr=stderr,
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

        self.assertEqual(code, 1)
        self.assertIn("file is too big", stderr.getvalue())
        client.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_peek_is_default_and_does_not_acknowledge(self) -> None:
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(7, 10, 1_700_000_000, text="peeked", origin=self.origin_user("Ada")),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox"],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_large_limit_requires_ack(self) -> None:
        stderr = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            code = cli.run(
                ["inbox", "--limit", "500"],
                stdout=io.StringIO(),
                stderr=stderr,
                environ={
                    "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                    "TELEGRAM_CHAT_ID": "99",
                },
            )

        self.assertEqual(code, 2)
        self.assertIn("requires --ack", stderr.getvalue())
        client_cls.assert_not_called()

    def test_inbox_large_json_limit_is_rejected(self) -> None:
        stderr = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            code = cli.run(
                ["inbox", "--limit", "500", "--ack", "--format", "json"],
                stdout=io.StringIO(),
                stderr=stderr,
                environ={
                    "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                    "TELEGRAM_CHAT_ID": "99",
                },
            )

        self.assertEqual(code, 2)
        self.assertIn("--format json", stderr.getvalue())
        client_cls.assert_not_called()

    def test_inbox_output_dash_keeps_stdout_behavior(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(1, 10, 1_700_000_000, text="stdout note", origin=self.origin_user("Ada")),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--format", "compact", "--output", "-"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertIn("stdout note", stdout.getvalue())
        self.assertNotIn("path=", stdout.getvalue())

    def test_inbox_output_directory_writes_private_file_and_receipt(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.get_updates.return_value = [
                    self.update(1, 10, 1_700_000_000, text="private note", origin=self.origin_user("Ada")),
                ]
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--format", "compact", "--output", tmp],
                        stdout=stdout,
                        stderr=io.StringIO(),
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

            files = list(output_dir.iterdir())
            self.assertEqual(code, 0)
            self.assertEqual(len(files), 1)
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
            self.assertIn("private note", files[0].read_text(encoding="utf-8"))
            self.assertIn("records=1 updates=1 format=compact", stdout.getvalue())
            self.assertIn("sha256=", stdout.getvalue())
            self.assertIn("sed -n '1,120p'", stdout.getvalue())
            self.assertIn("rm --", stdout.getvalue())
            self.assertNotIn("private note", stdout.getvalue())

    def test_inbox_output_rejects_existing_file_before_fetch(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "inbox.md"
            output_path.write_text("existing\n", encoding="utf-8")
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                code = cli.run(
                    ["inbox", "--output", str(output_path)],
                    stdout=io.StringIO(),
                    stderr=stderr,
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", stderr.getvalue())
        client_cls.return_value.get_updates.assert_not_called()

    def test_inbox_ack_reads_multiple_batches(self) -> None:
        stdout = io.StringIO()
        first_batch = [
            self.update(update_id, update_id, 1_700_000_000 + update_id, text=f"batch-one-{update_id}", origin=self.origin_user("Ada"))
            for update_id in range(1, 101)
        ]
        second_batch = [
            self.update(update_id, update_id, 1_700_000_000 + update_id, text=f"batch-two-{update_id}", origin=self.origin_user("Grace"))
            for update_id in range(101, 104)
        ]
        fetch_batches = [first_batch, second_batch]

        def get_updates(limit: int = 100, **kwargs: object) -> list[dict[str, object]]:
            if "offset" in kwargs:
                return []
            self.assertLessEqual(limit, cli.TELEGRAM_UPDATE_LIMIT)
            return fetch_batches.pop(0)

        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.side_effect = get_updates
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_200):
                code = cli.run(
                    ["inbox", "--limit", "103", "--ack"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertIn("batch-one-1", stdout.getvalue())
        self.assertIn("batch-two-103", stdout.getvalue())
        client_cls.return_value.get_updates.assert_has_calls(
            [
                mock.call(100, timeout=0, allowed_updates=["message"]),
                mock.call(1, offset=101, timeout=0, allowed_updates=["message"]),
                mock.call(3, timeout=0, allowed_updates=["message"]),
                mock.call(1, offset=104, timeout=0, allowed_updates=["message"]),
            ]
        )

    def test_inbox_ack_writes_large_jsonl_file_after_global_ordering(self) -> None:
        stdout = io.StringIO()
        events: list[str] = []
        first_batch = [
            self.update(
                update_id,
                update_id,
                1_700_000_000 + update_id,
                text=f"jsonl-one-{update_id}",
                origin=self.origin_user("Ada", date=1_700_001_000 + update_id),
            )
            for update_id in range(1, 101)
        ]
        second_batch = [
            self.update(101, 101, 1_700_000_101, text="jsonl-two-early", origin=self.origin_user("Grace", date=1_700_000_001)),
            self.update(102, 102, 1_700_000_102, text="jsonl-two-later", origin=self.origin_user("Grace", date=1_700_001_200)),
        ]
        fetch_batches = [first_batch, second_batch]

        def get_updates(limit: int = 100, **kwargs: object) -> list[dict[str, object]]:
            events.append("ack" if "offset" in kwargs else "fetch")
            if "offset" in kwargs:
                return []
            self.assertLessEqual(limit, cli.TELEGRAM_UPDATE_LIMIT)
            return fetch_batches.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.get_updates.side_effect = get_updates
                with mock.patch("agentgram_tg.cli.os.fsync", side_effect=lambda fd: events.append("fsync")):
                    with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_200):
                        code = cli.run(
                            ["inbox", "--limit", "103", "--ack", "--format", "jsonl", "--output", tmp],
                            stdout=stdout,
                            stderr=io.StringIO(),
                            environ={
                                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                                "TELEGRAM_CHAT_ID": "99",
                            },
                        )

            files = list(output_dir.iterdir())
            self.assertEqual(code, 0)
            self.assertEqual(events, ["fetch", "fsync", "ack", "fetch", "fsync", "ack", "fsync"])
            self.assertEqual(len(files), 1)
            lines = files[0].read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 102)
            self.assertEqual(json.loads(lines[0])["content"], "jsonl-two-early")
            self.assertEqual(json.loads(lines[1])["content"], "jsonl-one-1")
            self.assertEqual(json.loads(lines[-1])["content"], "jsonl-two-later")
            self.assertIn("records=102 updates=102 format=jsonl", stdout.getvalue())
            self.assertNotIn("jsonl-one-1", stdout.getvalue())

    def test_inbox_ack_large_refusal_flushes_staged_records(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        first_batch = [
            self.update(update_id, update_id, 1_700_000_000, text=f"kept-{update_id}", origin=self.origin_user("Ada"))
            for update_id in range(1, 101)
        ]
        second_batch = [
            self.update(101, 101, 1_700_000_000, text="plain before", origin=None),
            self.update(102, 102, 1_700_000_000, text="forwarded after", origin=self.origin_user("Grace")),
        ]
        fetch_batches = [first_batch, second_batch]

        def get_updates(limit: int = 100, **kwargs: object) -> list[dict[str, object]]:
            if "offset" in kwargs:
                return []
            self.assertLessEqual(limit, cli.TELEGRAM_UPDATE_LIMIT)
            return fetch_batches.pop(0)

        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.side_effect = get_updates
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--limit", "102", "--ack", "--format", "compact"],
                    stdout=stdout,
                    stderr=stderr,
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
        )

        self.assertEqual(code, 2)
        self.assertIn("kept-1", stdout.getvalue())
        self.assertIn("forwarded after", stdout.getvalue())
        self.assertNotIn("plain before", stdout.getvalue())
        self.assertIn("were not rendered", stderr.getvalue())
        self.assertNotIn("staged inbox records kept at", stderr.getvalue())

    def test_inbox_ack_stops_without_ack_when_batch_has_no_records(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(7, 10, 1_700_000_000, text="plain only", origin=None),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--limit", "200", "--ack"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), "No inbox messages found.")
        client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_ack_json_empty_output_stays_json_for_single_batch(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = []
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--ack", "--format", "json"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), [])
        client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_ack_consumes_after_successful_output(self) -> None:
        events: list[str] = []
        updates = [self.update(7, 10, 1_700_000_000, text="ack me", origin=self.origin_user("Ada"))]

        def get_updates(*args: object, **kwargs: object) -> list[dict[str, object]]:
            events.append("ack" if "offset" in kwargs else "fetch")
            return updates if "offset" not in kwargs else []

        class RecordingStdout(io.StringIO):
            def write(self, value: str) -> int:
                if value and (not events or events[-1] != "write"):
                    events.append("write")
                return super().write(value)

        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.side_effect = get_updates
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--ack"],
                    stdout=RecordingStdout(),
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(events, ["fetch", "write", "ack"])
        client_cls.return_value.get_updates.assert_has_calls(
            [
                mock.call(100, timeout=0, allowed_updates=["message"]),
                mock.call(1, offset=8, timeout=0, allowed_updates=["message"]),
            ]
        )

    def test_inbox_ack_does_not_consume_empty_output(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = []
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--ack"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().strip(), "No inbox messages found.")
        client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_ack_does_not_consume_when_rendering_fails(self) -> None:
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [
                self.update(7, 10, 1_700_000_000, text="do not ack", origin=self.origin_user("Ada")),
            ]
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                with mock.patch("agentgram_tg.cli.render_inbox_markdown", side_effect=RuntimeError("render failed")):
                    with self.assertRaisesRegex(RuntimeError, "render failed"):
                        cli.cmd_inbox(
                            argparse.Namespace(
                                chat_id=None,
                                limit=100,
                                since="24h",
                                include_plain=False,
                                output_format="markdown",
                                output=None,
                                ack=True,
                            ),
                            stdout=io.StringIO(),
                            environ={
                                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                                "TELEGRAM_CHAT_ID": "99",
                            },
                        )

        client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_ack_refuses_to_skip_filtered_updates(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        updates = [
            self.update(7, 10, 1_700_000_000, text="plain before", origin=None),
            self.update(8, 20, 1_700_000_000, text="forwarded after", origin=self.origin_user("Ada")),
        ]

        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = updates
            with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                code = cli.run(
                    ["inbox", "--ack"],
                    stdout=stdout,
                    stderr=stderr,
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 2)
        self.assertIn("forwarded after", stdout.getvalue())
        self.assertIn("were not rendered", stderr.getvalue())
        client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_inbox_ack_refusal_with_output_prints_cleanup_receipt(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        updates = [
            self.update(7, 10, 1_700_000_000, text="plain before", origin=None),
            self.update(8, 20, 1_700_000_000, text="forwarded after", origin=self.origin_user("Ada")),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.get_updates.return_value = updates
                with mock.patch("agentgram_tg.cli.time.time", return_value=1_700_000_001):
                    code = cli.run(
                        ["inbox", "--ack", "--output", tmp],
                        stdout=stdout,
                        stderr=stderr,
                        environ={
                            "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                            "TELEGRAM_CHAT_ID": "99",
                        },
                    )

            files = list(output_dir.iterdir())
            self.assertEqual(code, 2)
            self.assertEqual(len(files), 1)
            self.assertIn("forwarded after", files[0].read_text(encoding="utf-8"))
            self.assertIn("were not rendered", stderr.getvalue())
            self.assertIn("path=", stdout.getvalue())
            self.assertIn("delete after import: rm --", stdout.getvalue())
            self.assertNotIn("forwarded after", stdout.getvalue())
            client_cls.return_value.get_updates.assert_called_once_with(100, timeout=0, allowed_updates=["message"])

    def test_acknowledge_inbox_records_never_uses_negative_offset(self) -> None:
        client = mock.Mock()

        with self.assertRaisesRegex(cli.CliError, "negative offset"):
            cli.acknowledge_inbox_records(client, [{"update_id": -2}], [{"update_id": -2}])

        client.get_updates.assert_not_called()

    def update(
        self,
        update_id: int,
        message_id: int,
        date: int,
        *,
        chat_id: int = 99,
        text: str = "",
        origin: dict[str, object] | None,
        media: dict[str, object] | None = None,
    ) -> dict[str, object]:
        message: dict[str, object] = {
            "message_id": message_id,
            "date": date,
            "chat": {"id": chat_id, "type": "private", "first_name": "User"},
            "from": {"id": 555, "first_name": "Forwarder", "username": "forwarder"},
        }
        if text:
            message["text"] = text
        if media:
            message.update(media)
        if origin is not None:
            message["forward_origin"] = origin
        return {"update_id": update_id, "message": message}

    def origin_user(self, name: str, *, username: str = "", date: int = 1_700_000_000) -> dict[str, object]:
        user: dict[str, object] = {"id": 123, "first_name": name}
        if username:
            user["username"] = username
        return {"type": "user", "date": date, "sender_user": user}

    def origin_hidden_user(self, name: str, *, date: int = 1_700_000_000) -> dict[str, object]:
        return {"type": "hidden_user", "date": date, "sender_user_name": name}


class CliRunTests(unittest.TestCase):
    def test_help_lists_public_commands(self) -> None:
        output = cli.build_parser().format_help()
        for command in ("send", "send-file", "chat-id", "inbox", "download-file", "doctor", "update"):
            self.assertIn(command, output)

    def test_send_requires_token_without_leaking(self) -> None:
        stderr = io.StringIO()
        code = cli.run(["send", "hello"], stdout=io.StringIO(), stderr=stderr, environ={})

        self.assertEqual(code, 2)
        self.assertIn("TELEGRAM_BOT_TOKEN is required", stderr.getvalue())

    def test_send_rejects_long_text_by_default(self) -> None:
        stderr = io.StringIO()
        code = cli.run(
            ["send", "x" * (cli.MAX_TEXT_LENGTH + 1)],
            stdout=io.StringIO(),
            stderr=stderr,
            environ={
                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                "TELEGRAM_CHAT_ID": "99",
            },
        )

        self.assertEqual(code, 2)
        self.assertIn("message text is too long", stderr.getvalue())

    def test_send_uses_telegram_client(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.send_message.return_value = {"message_id": 42}
            code = cli.run(
                ["send", "--silent", "hello"],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz", "TELEGRAM_CHAT_ID": "99"},
            )

        self.assertEqual(code, 0)
        client_cls.return_value.send_message.assert_called_once_with(
            {"chat_id": "99", "text": "hello", "disable_notification": True}
        )
        self.assertEqual(stdout.getvalue().strip(), "sent message_id=42")

    def test_send_split_uses_telegram_client_for_each_chunk(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.send_message.side_effect = [
                {"message_id": 1},
                {"message_id": 2},
            ]
            with mock.patch("agentgram_tg.cli.split_message_text", return_value=["[1/2] hello", "[2/2] world"]):
                code = cli.run(
                    ["send", "--split", "--silent", "--no-preview", "hello", "world"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        self.assertEqual(client_cls.return_value.send_message.call_count, 2)
        client_cls.return_value.send_message.assert_has_calls(
            [
                mock.call(
                    {
                        "chat_id": "99",
                        "text": "[1/2] hello",
                        "disable_notification": True,
                        "link_preview_options": {"is_disabled": True},
                    }
                ),
                mock.call(
                    {
                        "chat_id": "99",
                        "text": "[2/2] world",
                        "disable_notification": True,
                        "link_preview_options": {"is_disabled": True},
                    }
                ),
            ]
        )
        self.assertEqual(stdout.getvalue().strip(), "sent messages count=2 message_ids=1,2")

    def test_send_split_rejects_parse_mode(self) -> None:
        stderr = io.StringIO()
        code = cli.run(
            ["send", "--split", "--parse-mode", "HTML", "<b>hello</b>"],
            stdout=io.StringIO(),
            stderr=stderr,
            environ={
                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                "TELEGRAM_CHAT_ID": "99",
            },
        )

        self.assertEqual(code, 2)
        self.assertIn("--split does not support --parse-mode", stderr.getvalue())

    def test_send_as_file_uses_temporary_document(self) -> None:
        stdout = io.StringIO()
        seen: dict[str, object] = {}

        def send_document(payload: dict[str, object], path: Path) -> dict[str, object]:
            seen["payload"] = payload
            seen["name"] = path.name
            seen["content"] = path.read_text(encoding="utf-8")
            seen["exists_during_call"] = path.exists()
            return {"message_id": 44}

        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.send_document.side_effect = send_document
            code = cli.run(
                ["send", "--as-file", "--filename", "report.md", "--silent", "#", "report"],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={
                    "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                    "TELEGRAM_CHAT_ID": "99",
                },
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen["payload"], {"chat_id": "99", "disable_notification": True})
        self.assertEqual(seen["name"], "report.md")
        self.assertEqual(seen["content"], "# report")
        self.assertTrue(seen["exists_during_call"])
        self.assertEqual(stdout.getvalue().strip(), "sent document message_id=44")

    def test_send_as_file_rejects_filename_without_mode(self) -> None:
        stderr = io.StringIO()
        code = cli.run(
            ["send", "--filename", "report.md", "hello"],
            stdout=io.StringIO(),
            stderr=stderr,
            environ={
                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                "TELEGRAM_CHAT_ID": "99",
            },
        )

        self.assertEqual(code, 2)
        self.assertIn("--filename requires --as-file", stderr.getvalue())

    def test_send_as_file_rejects_parse_mode(self) -> None:
        stderr = io.StringIO()
        code = cli.run(
            ["send", "--as-file", "--parse-mode", "MarkdownV2", "hello"],
            stdout=io.StringIO(),
            stderr=stderr,
            environ={
                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                "TELEGRAM_CHAT_ID": "99",
            },
        )

        self.assertEqual(code, 2)
        self.assertIn("--as-file does not support --parse-mode", stderr.getvalue())

    def test_send_rejects_malformed_token_without_traceback(self) -> None:
        stderr = io.StringIO()
        code = cli.run(
            ["send", "hello"],
            stdout=io.StringIO(),
            stderr=stderr,
            environ={"TELEGRAM_BOT_TOKEN": "abc def", "TELEGRAM_CHAT_ID": "99"},
        )

        self.assertEqual(code, 1)
        self.assertIn("token shape is invalid", stderr.getvalue())
        self.assertNotIn("abc def", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_send_file_uses_telegram_client(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text("# report\n", encoding="utf-8")
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.send_document.return_value = {"message_id": 43}
                code = cli.run(
                    [
                        "send-file",
                        "--caption",
                        "Report",
                        "--parse-mode",
                        "HTML",
                        "--silent",
                        str(path),
                    ],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={
                        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                        "TELEGRAM_CHAT_ID": "99",
                    },
                )

        self.assertEqual(code, 0)
        client_cls.return_value.send_document.assert_called_once_with(
            {
                "chat_id": "99",
                "caption": "Report",
                "parse_mode": "HTML",
                "disable_notification": True,
            },
            path,
        )
        self.assertEqual(stdout.getvalue().strip(), "sent document message_id=43")

    def test_send_file_uses_chat_id_override(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text("# report\n", encoding="utf-8")
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.send_document.return_value = {}
                code = cli.run(
                    ["send-file", "--chat-id", "123", str(path)],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
                )

        self.assertEqual(code, 0)
        client_cls.return_value.send_document.assert_called_once_with({"chat_id": "123"}, path)
        self.assertEqual(stdout.getvalue().strip(), "sent document")

    def test_send_file_requires_token_without_leaking(self) -> None:
        stderr = io.StringIO()
        code = cli.run(["send-file", "/tmp/report.md"], stdout=io.StringIO(), stderr=stderr, environ={})

        self.assertEqual(code, 2)
        self.assertIn("TELEGRAM_BOT_TOKEN is required", stderr.getvalue())

    def test_send_file_requires_chat_id(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text("# report\n", encoding="utf-8")
            code = cli.run(
                ["send-file", str(path)],
                stdout=io.StringIO(),
                stderr=stderr,
                environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
            )

        self.assertEqual(code, 2)
        self.assertIn("TELEGRAM_CHAT_ID is required", stderr.getvalue())

    def test_send_file_rejects_invalid_path_without_traceback(self) -> None:
        stderr = io.StringIO()
        code = cli.run(
            ["send-file", "/tmp/agentgram-missing-report.md"],
            stdout=io.StringIO(),
            stderr=stderr,
            environ={
                "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                "TELEGRAM_CHAT_ID": "99",
            },
        )

        self.assertEqual(code, 2)
        self.assertIn("file does not exist", stderr.getvalue())

    def test_download_file_uses_file_id_and_writes_receipt(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_file.return_value = {
                    "file_id": "file-id",
                    "file_unique_id": "file-u",
                    "file_path": "documents/report.txt",
                    "file_size": 5,
                }
                client.download_file.return_value = {
                    "path": str(target),
                    "bytes": 5,
                    "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                }
                code = cli.run(
                    ["download-file", "file-id", "--output", str(target)],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
                )

        self.assertEqual(code, 0)
        client.get_file.assert_called_once_with("file-id")
        client.download_file.assert_called_once_with(
            "documents/report.txt",
            target,
            expected_size=5,
            max_bytes=cli.MAX_DOWNLOAD_BYTES,
        )
        self.assertIn(f"path={target}", stdout.getvalue())
        self.assertIn("sha256=", stdout.getvalue())

    def test_download_file_rejects_missing_file_path(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.get_file.return_value = {"file_id": "file-id", "file_unique_id": "file-u"}
                code = cli.run(
                    ["download-file", "file-id", "--output", tmp],
                    stdout=io.StringIO(),
                    stderr=stderr,
                    environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
                )

        self.assertEqual(code, 2)
        self.assertIn("downloadable file_path", stderr.getvalue())

    def test_download_file_download_error_is_telegram_error(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client = client_cls.return_value
                client.get_file.return_value = {
                    "file_id": "file-id",
                    "file_path": "documents/report.txt",
                    "file_size": 5,
                }
                client.download_file.side_effect = TelegramError("Telegram file download failed: timeout")
                code = cli.run(
                    ["download-file", "file-id", "--output", str(target)],
                    stdout=io.StringIO(),
                    stderr=stderr,
                    environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
                )

        self.assertEqual(code, 1)
        self.assertIn("download failed", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_download_file_filename_requires_safe_file_name(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
                client_cls.return_value.get_file.return_value = {
                    "file_id": "file-id",
                    "file_path": "documents/report.txt",
                }
                code = cli.run(
                    ["download-file", "file-id", "--output", tmp, "--filename", "../secret.txt"],
                    stdout=io.StringIO(),
                    stderr=stderr,
                    environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
                )

        self.assertEqual(code, 2)
        self.assertIn("filename", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_send_file_rejects_malformed_token_without_traceback(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text("# report\n", encoding="utf-8")
            code = cli.run(
                ["send-file", str(path)],
                stdout=io.StringIO(),
                stderr=stderr,
                environ={"TELEGRAM_BOT_TOKEN": "abc def", "TELEGRAM_CHAT_ID": "99"},
            )

        self.assertEqual(code, 1)
        self.assertIn("token shape is invalid", stderr.getvalue())
        self.assertNotIn("abc def", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_chat_id_raw_prints_updates(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_updates.return_value = [{"message": {"chat": {"id": 1}}}]
            code = cli.run(
                ["chat-id", "--raw"],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), [{"message": {"chat": {"id": 1}}}])

    def test_doctor_requires_default_chat_id(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_me.return_value = {"username": "agentgram_bot"}
            code = cli.run(
                ["doctor", "--json"],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz"},
            )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        chat_check = next(item for item in payload["checks"] if item["name"] == "chat_id_env")
        self.assertTrue(chat_check["required"])
        self.assertFalse(chat_check["ok"])

    def test_doctor_treats_whitespace_chat_id_as_missing(self) -> None:
        stdout = io.StringIO()
        with mock.patch("agentgram_tg.cli.TelegramClient") as client_cls:
            client_cls.return_value.get_me.return_value = {"username": "agentgram_bot"}
            code = cli.run(
                ["doctor", "--json"],
                stdout=stdout,
                stderr=io.StringIO(),
                environ={
                    "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnopqrstuvwxyz",
                    "TELEGRAM_CHAT_ID": "   ",
                },
            )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        chat_check = next(item for item in payload["checks"] if item["name"] == "chat_id_env")
        self.assertFalse(chat_check["ok"])

    def test_doctor_rejects_malformed_token_without_traceback(self) -> None:
        stdout = io.StringIO()
        code = cli.run(
            ["doctor", "--json"],
            stdout=stdout,
            stderr=io.StringIO(),
            environ={"TELEGRAM_BOT_TOKEN": "abc def", "TELEGRAM_CHAT_ID": "99"},
        )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        get_me = next(item for item in payload["checks"] if item["name"] == "telegram_get_me")
        self.assertIn("token shape is invalid", get_me["detail"])
        self.assertNotIn("abc def", json.dumps(payload))

    def test_update_check_does_not_fetch(self) -> None:
        with mock.patch("agentgram_tg.cli.run_git") as run_git:
            run_git.side_effect = ["main", "origin/main", "0\t0"]

            status = cli.git_update_status(Path("/tmp/repo"))

        self.assertIn("up to date", status)
        commands = [call.args[1:] for call in run_git.call_args_list]
        self.assertNotIn(("fetch", "--quiet"), commands)

    def test_update_prints_codex_refresh_when_plugin_is_installed(self) -> None:
        with mock.patch("agentgram_tg.cli.detected_codex_agentgram_entry", return_value="agentgram@personal"):
            steps = cli.update_next_steps(Path("/opt/agentgram"))

        self.assertIn("codex plugin add agentgram@personal", "\n".join(steps))

    def test_codex_detection_ignores_not_installed_marketplace_entry(self) -> None:
        output = """PLUGIN                STATUS         VERSION  PATH
agentgram@personal    not installed           /root/plugins/agentgram
gitmoot@gitmoot-local installed, enabled 0.1.0 /root/.gitmoot/plugins/gitmoot
"""
        proc = subprocess.CompletedProcess(["codex", "plugin", "list"], 0, stdout=output, stderr="")
        with mock.patch("agentgram_tg.cli.subprocess.run", return_value=proc):
            detected = cli.detected_codex_agentgram_entry()

        self.assertIsNone(detected)

    def test_codex_detection_returns_installed_agentgram_entry(self) -> None:
        output = """PLUGIN             STATUS              VERSION PATH
agentgram@personal installed, enabled  0.1.0   /root/plugins/agentgram
"""
        proc = subprocess.CompletedProcess(["codex", "plugin", "list"], 0, stdout=output, stderr="")
        with mock.patch("agentgram_tg.cli.subprocess.run", return_value=proc):
            detected = cli.detected_codex_agentgram_entry()

        self.assertEqual(detected, "agentgram@personal")

    def test_origin_url_redacts_userinfo(self) -> None:
        self.assertEqual(
            cli.redact_url_userinfo("https://user:token@github.com/org/repo.git"),
            "https://github.com/org/repo.git",
        )


@unittest.skipUnless(has_writable_tempdir(), "requires a writable temporary directory")
class GitUpdateWorkflowTests(unittest.TestCase):
    def test_update_check_reports_no_remote_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self.git(repo, "init")

            status = cli.git_update_status(repo)

        self.assertIn("unknown update state", status)
        self.assertIn("no upstream configured", status)

    def test_update_check_reports_current_ahead_and_behind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, seed = self.create_origin(Path(tmp))
            checkout = Path(tmp) / "checkout"
            self.git(Path(tmp), "clone", str(origin), str(checkout))
            self.configure_user(checkout)

            self.assertIn("up to date", cli.git_update_status(checkout))

            (checkout / "local.txt").write_text("local\n", encoding="utf-8")
            self.git(checkout, "add", "local.txt")
            self.git(checkout, "commit", "-m", "local change")
            self.assertIn("ahead 1, behind 0", cli.git_update_status(checkout))

            self.git(checkout, "reset", "--hard", "origin/main")
            (seed / "remote.txt").write_text("remote\n", encoding="utf-8")
            self.git(seed, "add", "remote.txt")
            self.git(seed, "commit", "-m", "remote change")
            self.git(seed, "push")
            self.git(checkout, "fetch")
            self.assertIn("ahead 0, behind 1", cli.git_update_status(checkout))

    def test_update_refuses_dirty_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, _seed = self.create_origin(Path(tmp))
            checkout = Path(tmp) / "checkout"
            self.git(Path(tmp), "clone", str(origin), str(checkout))
            (checkout / "README.md").write_text("dirty\n", encoding="utf-8")
            stderr = io.StringIO()

            code = cli.run(["update", "--repo", str(checkout)], stdout=io.StringIO(), stderr=stderr, environ={})

        self.assertEqual(code, 2)
        self.assertIn("refusing to update", stderr.getvalue())

    def test_update_runs_fast_forward_pull_and_validates_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, seed = self.create_origin(Path(tmp))
            checkout = Path(tmp) / "checkout"
            self.git(Path(tmp), "clone", str(origin), str(checkout))
            (seed / "README.md").write_text("updated\n", encoding="utf-8")
            self.git(seed, "add", "README.md")
            self.git(seed, "commit", "-m", "remote update")
            self.git(seed, "push")
            stdout = io.StringIO()
            with mock.patch("agentgram_tg.cli.detected_codex_agentgram_entry", return_value=None):
                code = cli.run(["update", "--repo", str(checkout)], stdout=stdout, stderr=io.StringIO(), environ={})

            self.assertEqual(code, 0)
            self.assertIn("validation ok", stdout.getvalue())
            self.assertEqual((checkout / "README.md").read_text(encoding="utf-8"), "updated\n")

    def test_validate_checkout_accepts_current_repo_layout(self) -> None:
        cli.validate_checkout(ROOT)

    def test_update_rejects_non_agentgram_checkout_before_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, seed = self.create_plain_origin(Path(tmp))
            checkout = Path(tmp) / "checkout"
            self.git(Path(tmp), "clone", str(origin), str(checkout))
            (seed / "README.md").write_text("remote update\n", encoding="utf-8")
            self.git(seed, "add", "README.md")
            self.git(seed, "commit", "-m", "remote update")
            self.git(seed, "push")
            stderr = io.StringIO()

            code = cli.run(["update", "--repo", str(checkout)], stdout=io.StringIO(), stderr=stderr, environ={})

            self.assertEqual(code, 2)
            self.assertIn("checkout validation failed", stderr.getvalue())
            self.assertEqual((checkout / "README.md").read_text(encoding="utf-8"), "plain\n")

    def create_origin(self, root: Path) -> tuple[Path, Path]:
        origin = root / "origin.git"
        seed = root / "seed"
        self.git(root, "init", "--bare", str(origin))
        seed.mkdir()
        self.git(seed, "init")
        self.git(seed, "checkout", "-b", "main")
        self.configure_user(seed)
        self.write_agentgram_layout(seed, readme="initial\n")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-m", "initial")
        self.git(seed, "remote", "add", "origin", str(origin))
        self.git(seed, "push", "-u", "origin", "main")
        self.git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        return origin, seed

    def create_plain_origin(self, root: Path) -> tuple[Path, Path]:
        origin = root / "plain-origin.git"
        seed = root / "plain-seed"
        self.git(root, "init", "--bare", str(origin))
        seed.mkdir()
        self.git(seed, "init")
        self.git(seed, "checkout", "-b", "main")
        self.configure_user(seed)
        (seed / "README.md").write_text("plain\n", encoding="utf-8")
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-m", "initial")
        self.git(seed, "remote", "add", "origin", str(origin))
        self.git(seed, "push", "-u", "origin", "main")
        self.git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        return origin, seed

    def write_agentgram_layout(self, repo: Path, *, readme: str) -> None:
        (repo / "bin").mkdir(parents=True)
        executable = repo / "bin" / "agentgram"
        executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        executable.chmod(0o755)
        (repo / ".codex-plugin").mkdir()
        (repo / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "agentgram", "skills": "./skills/"}),
            encoding="utf-8",
        )
        (repo / "skills" / "agentgram").mkdir(parents=True)
        (repo / "skills" / "agentgram" / "SKILL.md").write_text("---\nname: agentgram\n---\n", encoding="utf-8")
        (repo / "src" / "agentgram_tg").mkdir(parents=True)
        (repo / "src" / "agentgram_tg" / "cli.py").write_text("# cli\n", encoding="utf-8")
        (repo / "README.md").write_text(readme, encoding="utf-8")

    def configure_user(self, repo: Path) -> None:
        self.git(repo, "config", "user.email", "agentgram@example.invalid")
        self.git(repo, "config", "user.name", "Agentgram Tests")

    def git(self, repo: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout.strip()


class TelegramClientTests(unittest.TestCase):
    def test_request_posts_json_and_returns_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": {"message_id": 7}}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
            result = TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").request("sendMessage", {"text": "hi"})

        self.assertEqual(result, {"message_id": 7})
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertEqual(json.loads(req.data.decode("utf-8")), {"text": "hi"})

    def test_request_rejects_non_object_json_response(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'["not", "an", "object"]'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
            with self.assertRaisesRegex(TelegramError, "unexpected JSON response"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").request("sendMessage", {})

    def test_get_me_rejects_unexpected_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": []}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
            with self.assertRaisesRegex(TelegramError, "getMe returned an unexpected result"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_me()

    def test_get_updates_posts_default_payload(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": []}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
            result = TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates()

        self.assertEqual(result, [])
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/getUpdates")
        self.assertEqual(json.loads(req.data.decode("utf-8")), {"limit": 20, "timeout": 0})

    def test_get_updates_posts_explicit_payload(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": [{"update_id": 10}]}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
            result = TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates(
                100,
                offset=123,
                timeout=5,
                allowed_updates=["message"],
            )

        self.assertEqual(result, [{"update_id": 10}])
        req = urlopen.call_args.args[0]
        self.assertEqual(
            json.loads(req.data.decode("utf-8")),
            {
                "allowed_updates": ["message"],
                "limit": 100,
                "offset": 123,
                "timeout": 5,
            },
        )

    def test_get_updates_extends_http_timeout_for_long_polling(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": []}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
            TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates(timeout=30)

        self.assertEqual(urlopen.call_args.kwargs["timeout"], 35.0)

    def test_get_updates_rejects_invalid_limit_before_request(self) -> None:
        with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
            with self.assertRaisesRegex(TelegramError, "limit must be from 1 to 100"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates(0)

        urlopen.assert_not_called()

    def test_get_updates_rejects_invalid_timeout_before_request(self) -> None:
        with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
            with self.assertRaisesRegex(TelegramError, "timeout must be a non-negative integer"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates(timeout=-1)

        urlopen.assert_not_called()

    def test_get_updates_rejects_non_string_allowed_update(self) -> None:
        with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
            with self.assertRaisesRegex(TelegramError, "allowed_updates must be a list of strings"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates(allowed_updates=["message", 7])

        urlopen.assert_not_called()

    def test_get_updates_rejects_unexpected_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": {}}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
            with self.assertRaisesRegex(TelegramError, "getUpdates returned an unexpected result"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_updates()

    def test_get_file_posts_file_id_and_returns_valid_file(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"ok": true, "result": {"file_id": "file-id", "file_unique_id": "file-u", '
            b'"file_size": 5, "file_path": "documents/report.txt"}}'
        )

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
            result = TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_file("file-id")

        self.assertEqual(result["file_path"], "documents/report.txt")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/getFile")
        self.assertEqual(json.loads(req.data.decode("utf-8")), {"file_id": "file-id"})

    def test_get_file_rejects_unexpected_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": []}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
            with self.assertRaisesRegex(TelegramError, "getFile returned an unexpected result"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").get_file("file-id")

    def test_download_file_writes_private_file_and_returns_receipt(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b"hello", b""]
        token = "123456:abcdefghijklmnopqrstuvwxyz"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
                result = TelegramClient(token).download_file(
                    "documents/report.txt",
                    target,
                    expected_size=5,
                    max_bytes=20,
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

        self.assertEqual(result["bytes"], 5)
        self.assertEqual(result["sha256"], "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, f"https://api.telegram.org/file/bot{token}/documents/report.txt")

    def test_download_file_rejects_oversized_expected_size_before_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "large.bin"
            with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
                with self.assertRaisesRegex(TelegramError, "file is too large"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").download_file(
                        "documents/large.bin",
                        target,
                        expected_size=21,
                        max_bytes=20,
                    )

        urlopen.assert_not_called()
        self.assertFalse(target.exists())

    def test_download_file_rejects_max_bytes_above_public_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "large.bin"
            with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
                with self.assertRaisesRegex(TelegramError, "cannot exceed"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").download_file(
                        "documents/large.bin",
                        target,
                        max_bytes=cli.MAX_DOWNLOAD_BYTES + 1,
                    )

        urlopen.assert_not_called()
        self.assertFalse(target.exists())

    def test_download_file_refuses_existing_destination_before_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            target.write_text("existing\n", encoding="utf-8")
            with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
                with self.assertRaisesRegex(TelegramError, "refusing to overwrite"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").download_file(
                        "documents/report.txt",
                        target,
                        max_bytes=20,
                    )

        urlopen.assert_not_called()

    def test_download_file_removes_partial_file_when_size_exceeds_limit(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b"0123456789", b"0123456789", b"x", b""]

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "large.bin"
            with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
                with self.assertRaisesRegex(TelegramError, "file is too large"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").download_file(
                        "documents/large.bin",
                        target,
                        max_bytes=20,
                    )
            self.assertFalse(target.exists())

    def test_download_file_http_error_redacts_token(self) -> None:
        token = "123456:abcdefghijklmnopqrstuvwxyz"
        http_error = error.HTTPError(
            f"https://api.telegram.org/file/bot{token}/documents/report.txt",
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"ok": false, "description": "token 123456:abcdefghijklmnopqrstuvwxyz invalid"}'),
        )

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.telegram.request.urlopen", side_effect=http_error):
                with self.assertRaises(TelegramError) as caught:
                    TelegramClient(token).download_file("documents/report.txt", target)

        self.assertNotIn(token, str(caught.exception))
        self.assertIn("<redacted>", str(caught.exception))
        self.assertFalse(target.exists())

    def test_download_file_interrupted_read_becomes_telegram_error(self) -> None:
        import http.client

        class InterruptedResponse:
            def __enter__(self) -> "InterruptedResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, size: int) -> bytes:
                raise http.client.IncompleteRead(b"abc")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.txt"
            with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=InterruptedResponse()):
                with self.assertRaisesRegex(TelegramError, "download failed"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").download_file("documents/report.txt", target)
            self.assertFalse(target.exists())

    def test_encode_multipart_form_includes_fields_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("hello\n", encoding="utf-8")

            body, content_type = encode_multipart_form(
                {"chat_id": "99", "caption": "Report", "disable_notification": True},
                "document",
                path,
                boundary="agentgram-test-boundary",
            )

        decoded = body.decode("utf-8")
        self.assertEqual(content_type, "multipart/form-data; boundary=agentgram-test-boundary")
        self.assertIn('name="chat_id"', decoded)
        self.assertIn("\r\n99\r\n", decoded)
        self.assertIn('name="caption"', decoded)
        self.assertIn("\r\nReport\r\n", decoded)
        self.assertIn('name="disable_notification"', decoded)
        self.assertIn("\r\ntrue\r\n", decoded)
        self.assertIn('name="document"; filename="report.txt"', decoded)
        self.assertIn("Content-Type: text/plain", decoded)
        self.assertIn("\r\nhello\n\r\n", decoded)

    def test_send_document_posts_multipart_and_returns_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": {"message_id": 8}}'
        token = "123456:abcdefghijklmnopqrstuvwxyz"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("hello\n", encoding="utf-8")
            with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response) as urlopen:
                result = TelegramClient(token).send_document({"chat_id": "99", "caption": "Report"}, path)

        self.assertEqual(result, {"message_id": 8})
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, f"https://api.telegram.org/bot{token}/sendDocument")
        self.assertTrue(req.headers["Content-type"].startswith("multipart/form-data; boundary=agentgram-"))
        self.assertIn(b'name="document"; filename="report.txt"', req.data)
        self.assertIn(b"hello\n", req.data)
        self.assertNotIn(token.encode("utf-8"), req.data)

    def test_send_document_rejects_oversized_file_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.txt"
            with path.open("wb") as handle:
                handle.truncate(cli.MAX_DOCUMENT_BYTES + 1)
            with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
                with self.assertRaisesRegex(TelegramError, "file is too large"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").send_document({"chat_id": "99"}, path)

        urlopen.assert_not_called()

    def test_send_document_rejects_missing_file_before_upload(self) -> None:
        with mock.patch("agentgram_tg.telegram.request.urlopen") as urlopen:
            with self.assertRaisesRegex(TelegramError, "file does not exist"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").send_document(
                    {"chat_id": "99"},
                    Path("/tmp/agentgram-missing-document"),
                )

        urlopen.assert_not_called()

    def test_send_document_rejects_unexpected_result(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true, "result": []}'

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("hello\n", encoding="utf-8")
            with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
                with self.assertRaisesRegex(TelegramError, "sendDocument returned an unexpected result"):
                    TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").send_document({"chat_id": "99"}, path)

    def test_send_document_http_error_redacts_token(self) -> None:
        token = "123456:abcdefghijklmnopqrstuvwxyz"
        http_error = error.HTTPError(
            f"https://api.telegram.org/bot{token}/sendDocument",
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"ok": false, "description": "token 123456:abcdefghijklmnopqrstuvwxyz invalid"}'),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text("hello\n", encoding="utf-8")
            with mock.patch("agentgram_tg.telegram.request.urlopen", side_effect=http_error):
                with self.assertRaises(TelegramError) as caught:
                    TelegramClient(token).send_document({"chat_id": "99"}, path)

        self.assertNotIn(token, str(caught.exception))
        self.assertIn("<redacted>", str(caught.exception))

    def test_telegram_error_response_uses_description(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": false, "description": "Bad Request: chat not found"}'

        with mock.patch("agentgram_tg.telegram.request.urlopen", return_value=response):
            with self.assertRaisesRegex(TelegramError, "chat not found"):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").request("sendMessage", {})

    def test_http_error_redacts_token(self) -> None:
        token = "123456:abcdefghijklmnopqrstuvwxyz"
        http_error = error.HTTPError(
            f"https://api.telegram.org/bot{token}/sendMessage",
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"ok": false, "description": "token 123456:abcdefghijklmnopqrstuvwxyz invalid"}'),
        )

        with mock.patch("agentgram_tg.telegram.request.urlopen", side_effect=http_error):
            with self.assertRaises(TelegramError) as caught:
                TelegramClient(token).request("sendMessage", {})

        self.assertNotIn(token, str(caught.exception))
        self.assertIn("<redacted>", str(caught.exception))

    def test_http_error_handles_non_object_json(self) -> None:
        http_error = error.HTTPError(
            "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwxyz/sendMessage",
            502,
            "Bad Gateway",
            hdrs=None,
            fp=io.BytesIO(b'["bad", "gateway"]'),
        )

        with mock.patch("agentgram_tg.telegram.request.urlopen", side_effect=http_error):
            with self.assertRaisesRegex(TelegramError, r'\["bad", "gateway"\]'):
                TelegramClient("123456:abcdefghijklmnopqrstuvwxyz").request("sendMessage", {})

    def test_redact_token(self) -> None:
        self.assertEqual(redact_token("abc token abc", "token"), "abc <redacted> abc")


if __name__ == "__main__":
    unittest.main()
