from __future__ import annotations

import io
import json
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
from agentgram_tg.telegram import TelegramClient, TelegramError, redact_token


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


class CliRunTests(unittest.TestCase):
    def test_help_lists_public_commands(self) -> None:
        output = cli.build_parser().format_help()
        for command in ("send", "chat-id", "doctor", "update"):
            self.assertIn(command, output)

    def test_send_requires_token_without_leaking(self) -> None:
        stderr = io.StringIO()
        code = cli.run(["send", "hello"], stdout=io.StringIO(), stderr=stderr, environ={})

        self.assertEqual(code, 2)
        self.assertIn("TELEGRAM_BOT_TOKEN is required", stderr.getvalue())

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

    def test_redact_token(self) -> None:
        self.assertEqual(redact_token("abc token abc", "token"), "abc <redacted> abc")


if __name__ == "__main__":
    unittest.main()
