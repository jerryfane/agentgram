# Agentgram Forwarded Inbox Context

Implement the plan task by task. Each task must be developed, reviewed, opened
as its own pull request, merged, and verified before moving on, unless tasks are
explicitly safe to run in parallel.

Agentgram should let Codex and other local AI agents read recent Telegram
messages that a user manually forwarded into the Agentgram bot chat. The user
workflow is: forward selected group, channel, or private-chat messages to the
bot; ask an agent to read the recent forwarded messages; the agent runs
`agentgram inbox`; Agentgram prints a clean transcript to stdout for the current
agent session. This goal uses the Telegram Bot API only. It excludes MTProto
user sessions, background scraping, webhook receivers, full Telegram chat
history, and any local message-content database.

Tracked feature issue: https://github.com/jerryfane/agentgram/issues/13

Verified planning assumptions:

- Telegram Bot API `getUpdates` is one of two mutually exclusive update
  delivery modes. Pending updates are stored until received, but not longer than
  24 hours.
- `getUpdates` accepts `limit` values from 1 to 100 and an update is confirmed
  when called with an offset greater than that update's `update_id`.
- Negative offsets can retrieve updates from the end of the queue while
  forgetting previous pending updates, so Agentgram must not use negative
  offsets by default.
- Forwarded messages can expose `message.forward_origin` as
  `MessageOriginUser`, `MessageOriginHiddenUser`, `MessageOriginChat`, or
  `MessageOriginChannel`. Sender privacy can hide stable user identity.

## Core Rules

- Work one task at a time in the listed order by default.
- If tasks are independent, have disjoint file ownership, and do not depend on
  each other's results, they may be done in parallel on separate branches.
- Do not start dependent work until the prerequisite task has passed checks,
  passed `codex exec review --uncommitted`, been pushed, opened as a PR, merged,
  and verified on the target branch.
- Do not commit generated data, reports, caches, build artifacts, secrets,
  credentials, session archives, cloned helper repos, local plugin build output,
  message transcripts, Telegram update dumps, or large outputs unless the plan
  explicitly says they are intended tracked fixtures/artifacts.
- Preserve existing behavior unless the current task explicitly changes it.
- Keep changes clean, scoped, and organized. Avoid broad rewrites.
- Avoid code duplication. When repeated logic appears, extract small reusable
  helpers that match existing repo patterns.
- If implementation depends on external APIs, docs, CLIs, data formats,
  generated scripts, installers, service launchers, subprocess calls, env vars,
  config formats, or third-party libraries, verify the real contract with local
  commands and/or official sources before editing.

## Before Starting

1. Inspect current repo state with:
   - `git status --short`
   - current branch
   - current remote
2. If the target branch is unclear, the remote looks wrong, or the worktree has
   unrelated existing changes that make task commits ambiguous, stop and ask
   before continuing.
3. Confirm the target base branch from the current repo. If unspecified, use the
   current branch as the base.
4. Inspect relevant existing patterns before editing:
   - `src/agentgram_tg/telegram.py`
   - `src/agentgram_tg/cli.py`
   - `tests/test_cli.py`
   - `skills/agentgram/SKILL.md`
   - packaged plugin mirror under `plugins/agentgram/`
5. Verify PR tooling is available before the first PR:
   - `gh auth status`
   - repo remote resolves to `https://github.com/jerryfane/agentgram.git`
6. Verify official Telegram Bot API contracts before implementation:
   - `https://core.telegram.org/bots/api#getupdates`
   - `https://core.telegram.org/bots/api#message`
   - `https://core.telegram.org/bots/api#messageorigin`

## Per-Task Branch Workflow

1. Confirm the current task's scope.
2. Create a task branch from the latest target base branch.
3. Implement only that task.
4. Add or update focused tests/checks appropriate to the task.
5. Run focused tests for touched modules.
6. Run broader checks when the task touches shared behavior, CLI/API surfaces,
   generated scripts, installers, docs build systems, or user-facing workflows.
7. For CLI, subprocess, env propagation, generated-script, or installer changes,
   include an operational smoke test or direct contract check. Syntax checks
   alone are not enough.
8. Identify every repository where files changed. In each changed repo, run:
   `codex exec review --uncommitted`
9. Preserve the exact raw review output per repo.

## Review-Fix Loop

1. If review finds issues, do not only patch the literal line.
2. Identify the underlying invariant/class of bug.
3. Audit nearby and sibling paths for the same issue.
4. Write a concise fix plan using:

   ```text
   Review found these issues: <<PASTE RAW REVIEW RESULTS BY REPO>>.
   For each issue, identify the underlying invariant/class of bug, audit sibling
   paths for the same issue, and plan the smallest safe fix. Verify external
   assumptions with local commands and/or official sources. Preserve repo
   patterns, avoid unnecessary refactors, and list tests/checks per repo.
   ```

5. Execute the fix plan.
6. Re-run focused tests/checks and `codex exec review --uncommitted` in every
   repo with uncommitted changes.
7. Repeat until the final raw review output contains no findings, or stop if
   blocked or if a finding is incorrect after verification.

## Commit Gate

1. Before committing, run `git diff --check` and inspect the final diff.
2. Commit only the current task's intended tracked changes.
3. Use the commit message specified by the plan. If the plan does not specify
   one, use a concise conventional message that describes only the current task.
4. Push the task branch.
5. Verify the task branch worktree is clean after push, except for
   intentionally ignored generated files.

## Pull Request Gate

1. Create one PR for the current task.
2. The PR title must describe only the current task.
3. The PR body must include:
   - WHAT: what was changed
   - WHY: why the task was needed
   - CHANGES: concrete implementation changes
   - RESULTS: tests/checks/review results
   - RISK: skipped checks, blockers, or residual risk
4. Include the exact raw final `codex exec review --uncommitted` output for each
   changed repo in the PR body.
5. If CI or required checks exist, wait for them and fix failures before merge.
6. Merge the PR using the repository's configured/preferred merge method. If no
   preference is discoverable, use squash merge for a clean task-level history.
7. After merge, update the local target base branch and verify the worktree is
   clean.
8. Record the PR number, PR URL, branch name, and merged commit hash.
9. Delete the task branch after merge only if the repository normally does so or
   the merge command supports safe branch deletion.

## Final Response After All Tasks

- List completed tasks.
- For each task, list branch, PR URL, merge status, and merged commit hash.
- List tests/checks run.
- Include exact final raw `codex exec review --uncommitted` output for the last
  task/repo.
- Mention skipped checks, blockers, or residual risk.
- Do not claim interactive `/review` is clean. Say:
  `codex exec review is clean; ready for manual /review.`

## Implementation Tasks

### Task 1: Add Update Retrieval Foundation

Scope:

- Extend `TelegramClient.get_updates` so callers can pass:
  - `limit`
  - `offset`
  - `timeout`
  - `allowed_updates`
- Keep `chat-id` behavior unchanged while letting inbox use the richer call.
- Validate `limit` locally as 1-100.
- Keep response-shape validation and token redaction consistent with existing
  `send_message`, `send_document`, and `get_me`.
- Do not add third-party dependencies.

Acceptance criteria:

- Existing `agentgram chat-id` tests and behavior still pass.
- A caller can request only message updates with `allowed_updates=["message"]`.
- Invalid limits fail locally with a clear user-correctable error.
- Telegram errors remain redacted and do not leak the bot token.

Tests/checks:

- Unit tests for `get_updates` payload construction with default and explicit
  parameters.
- Unit tests for invalid `limit` bounds.
- Unit tests that non-list Telegram results still fail cleanly.
- `python3 -m unittest tests.test_cli.TelegramClientTests -v`
- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
feat: add configurable telegram update retrieval
```

### Task 2: Add Inbox Parsing, Filtering, and Rendering

Scope:

- Add a public CLI command:

  ```sh
  agentgram inbox [--chat-id <id>] [--limit <1-100>] [--since <duration>]
                  [--forwarded-only | --include-plain]
                  [--format markdown|json]
  ```

- Default behavior should be equivalent to:

  ```sh
  agentgram inbox --limit 100 --since 24h --forwarded-only --format markdown
  ```

- Read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` by default.
- Fetch pending updates with Telegram `getUpdates`, `timeout=0`, and
  `allowed_updates=["message"]`.
- Filter to the configured chat id unless `--chat-id` overrides it.
- Filter forwarded messages by default. `--include-plain` should include direct
  non-forwarded notes sent to the bot as well.
- Parse durations such as `15m`, `3h`, and `1d`.
- Extract readable content from `text`, `caption`, and concise media metadata
  when no text/caption exists.
- Render updates chronologically.
- Render both the Telegram user who forwarded the message to the bot and the
  original source from `forward_origin` when present.
- Handle `MessageOrigin` variants:
  - `user`: render known original user from `sender_user`
  - `hidden_user`: render privacy-hidden sender using `sender_user_name`
  - `chat`: render source chat and optional `author_signature`
  - `channel`: render channel chat, original message id, and optional
    `author_signature`
- Mark hidden or uncertain authorship clearly.

Acceptance criteria:

- `agentgram inbox --help` documents all options in this task.
- `agentgram inbox` prints a markdown transcript from mocked forwarded updates.
- `--forwarded-only` excludes direct non-forwarded messages.
- `--include-plain` includes direct non-forwarded messages.
- `--since` filters by message/update timestamp.
- `--format json` emits stable machine-readable records.
- Forward origin rendering covers `user`, `hidden_user`, `chat`, and `channel`.
- No message content is written to local files.

Tests/checks:

- CLI unit tests for default inbox behavior.
- Unit tests for chat filtering, forwarded-only filtering, include-plain mode,
  since filtering, and chronological ordering.
- Unit tests for markdown and JSON rendering.
- Unit tests for text, caption, and media-summary extraction.
- Unit tests for all four `MessageOrigin` variants and missing/hidden origin.
- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
feat: add forwarded inbox transcript command
```

### Task 3: Add Safe Ack and Peek Semantics

Scope:

- Add inbox acknowledgement controls:

  ```sh
  agentgram inbox --peek
  agentgram inbox --ack
  ```

- Default to `--peek` so first use does not discard forwarded messages.
- `--peek` must not call `getUpdates` with an acknowledging offset after output.
- `--ack` must acknowledge only after successful filtering and output.
- Acknowledge by calling `getUpdates` with `offset = max_update_id + 1`,
  `limit = 1`, and `timeout = 0`.
- Never use negative offsets for inbox.
- Do not write message contents locally.
- If durable state is needed, store only the last acknowledged `update_id` in a
  small config file, never message text, captions, sender names, or raw updates.
- Surface webhook/update-queue conflicts as clear Telegram errors if Telegram
  returns them.

Acceptance criteria:

- `--peek` can be run repeatedly against the same mocked update queue without
  issuing an acknowledging offset.
- `--ack` issues one acknowledgement call only after successful transcript
  output.
- `--ack` does not acknowledge updates when rendering/filtering fails.
- Empty inbox output does not acknowledge anything.
- No message body, caption, raw update JSON, sender name, or transcript is
  written to disk.

Tests/checks:

- Unit tests for peek default behavior.
- Unit tests for ack success, ack after-output ordering, and no-ack on failure.
- Unit tests that negative offsets are not used.
- Unit tests or assertions around any state-file content if a state file is
  introduced.
- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
feat: add safe inbox acknowledgement mode
```

### Task 4: Update Agent Instructions, Docs, and Release Metadata

Scope:

- Update root and packaged plugin `skills/agentgram/SKILL.md` so agents know:
  - if the user says "read the recent messages I forwarded to you", run
    `agentgram inbox`
  - if the user asks for "last 100", run `agentgram inbox --limit 100`
  - if the user asks for "last 3h", run `agentgram inbox --since 3h`
  - use `--include-plain` when the user says they also sent direct notes to the
    bot
  - use `--ack` only after successful import, or when the user asks to consume
    the forwarded messages
- Update README and packaged plugin README with the forwarding workflow,
  examples, limitations, and privacy behavior.
- Document that this is pending Bot API updates only, not full Telegram chat
  history.
- Document that pending updates can expire, can be consumed by another process,
  and cannot be read with `getUpdates` while a webhook is active.
- Document that original authorship depends on Telegram `forward_origin` and
  sender privacy settings.
- Bump release metadata only if this task is preparing a release PR. Otherwise,
  leave version changes for a separate release task.

Acceptance criteria:

- Agent-facing skill instructions accurately map natural language inbox requests
  to the new CLI commands.
- README includes a concise "Forwarded Inbox" section with examples.
- README explains no message-content storage.
- README explains `--peek` vs `--ack`.
- Root source docs and packaged plugin mirror stay in sync.
- Existing send, send-file, long-text, chat-id, doctor, and update docs remain
  accurate.

Tests/checks:

- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `python3 /root/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /root/agentgram`
- `python3 /root/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /root/agentgram/plugins/agentgram`
- `PYTHONDONTWRITEBYTECODE=1 bin/agentgram inbox --help`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
docs: teach agents to read forwarded inbox context
```

## Goal Prompt

```text
/goal Use the Gitmoot goal in docs/goal-forwarded-inbox-context.md for jerryfane/agentgram. Implement the tasks in order. Start with Task 1 only, create a task branch from the current default branch, preserve existing send, send-file, long-text, chat-id, doctor, and update behavior, verify Telegram Bot API getUpdates and MessageOrigin contracts from official sources before editing, run focused tests plus codex exec review --uncommitted, open and merge one PR before moving to the next task, and do not commit Telegram tokens, message transcripts, raw update dumps, generated local plugin output, or other secrets.
```
