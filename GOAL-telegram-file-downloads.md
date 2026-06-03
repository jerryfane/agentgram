# Telegram File Downloads

Implement the plan task by task. Each task must be developed, reviewed, opened
as its own pull request, merged, and verified before moving on, unless tasks are
explicitly safe to run in parallel.

Add Agentgram support for downloading files that a user sends or forwards to
the Telegram bot. The intended user-facing outcome is that an agent can read
recent bot inbox messages, download attached files into a private local path,
and then inspect those files when the user asks. This touches the Telegram Bot
API client, inbox extraction/rendering, CLI commands, docs, plugin mirrors, and
tests. This goal does not implement MTProto user sessions, full Telegram chat
history, webhook ingestion, malware scanning, archive extraction, or a local
Telegram Bot API server deployment.

External contract notes:

- Telegram Bot API `getUpdates` returns pending message updates and confirms
  updates by offset.
- Telegram Bot API `getFile` accepts `file_id`, returns a temporary
  downloadable `file_path`, and public Bot API downloads are limited to 20 MB.
- `getFile` may not preserve original filename or MIME type, so Agentgram must
  preserve filename and MIME metadata from the original message update when it
  is available.
- Telegram's local Bot API server is the official future path for large
  downloads, but this goal should keep the default implementation on the public
  Bot API.

## Core Rules

- Work one task at a time in the listed order by default.
- If tasks are independent, have disjoint file ownership, and do not depend on
  each other's results, they may be done in parallel on separate branches.
- Do not start dependent work until the prerequisite task has passed checks,
  passed `codex exec review --uncommitted`, been pushed, opened as a PR, merged,
  and verified on the target branch.
- Do not commit generated data, reports, caches, build artifacts, secrets,
  credentials, session archives, cloned helper repos, local plugin build output,
  or large outputs unless the plan explicitly says they are intended tracked
  fixtures/artifacts.
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
4. Inspect relevant existing patterns before editing.
5. Verify PR tooling is available before the first PR:
   - `gh auth status`
   - repo remote resolves to the expected GitHub repository

## Per-Task Branch Workflow

1. Confirm the current task's scope.
2. Create a task branch from the latest target base branch.
3. Implement only that task.
4. Add or update focused tests/checks appropriate to the task.
5. Run focused tests for touched modules.
6. Run broader checks when the task touches shared behavior, CLI/API surfaces,
   data/model/evaluation logic, generated scripts, installers, service
   launchers, docs build systems, or user-facing workflows.
7. For wrapper, installer, CLI, subprocess, generated-script, env propagation,
   service-launcher, or deployment changes, include an operational smoke test or
   direct contract check. Syntax checks alone are not enough.
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
5. Verify the task branch worktree is clean after push, except for intentionally
   ignored generated files.

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

## Parallel Task Rules

- Parallelize only when tasks are independent, have disjoint file ownership, and
  can be reviewed and merged without order-dependent assumptions.
- Use a separate branch per task.
- Clearly assign each branch a task number and file ownership.
- Do not duplicate work across branches.
- If parallel branches conflict after one PR merges, rebase or update the
  remaining branch on the latest target base and re-run its checks/review.
- If a task becomes dependent on another task, stop treating it as parallel and
  merge the dependency first.

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

### Task 1: Add Telegram File Download Client Primitives

Scope:

- Add Telegram client support for `getFile(file_id)`.
- Add a safe download helper that builds the Bot API file URL without printing
  or logging it, streams bytes to disk, verifies the byte count when known, and
  returns metadata.
- Add filename/path helpers that sanitize Telegram-provided names, reject path
  traversal, create files with `0600`, avoid overwrites, and produce deterministic
  fallback names from media kind, message id, and `file_unique_id` or `file_id`.
- Keep the public Bot API default max download size at 20 MB. Allow a smaller
  caller-provided `--max-file-bytes`, but do not silently exceed 20 MB unless a
  future local Bot API configuration is explicitly implemented.

Acceptance criteria:

- `TelegramClient.get_file(file_id)` returns a validated Telegram File object.
- `TelegramClient.download_file(file_path, destination, expected_size=None)`
  writes a private local file and never exposes the bot token in stdout, stderr,
  exceptions, receipts, or test output.
- Existing send and inbox behavior remains unchanged.

Tests/checks:

- Unit tests for `getFile` payload/response validation.
- Unit tests for token redaction on download URL or HTTP errors.
- Unit tests for filename sanitization, no-overwrite behavior, private file
  permissions, and size-limit refusal.
- Run `python3 -m unittest discover -s tests -v`.
- Run `git diff --check`.
- Run `codex exec review --uncommitted`.

Suggested commit message:

`feat: add telegram file download primitives`

### Task 2: Enrich Inbox Records With File Metadata

Scope:

- Extend inbox extraction so file-bearing messages expose structured attachment
  metadata in JSON/JSONL records while preserving current human-readable
  `content` strings.
- Support at least `document`, largest `photo` variant, `audio`, `video`,
  `animation`, `voice`, and `video_note`.
- Include attachment fields such as `kind`, `file_id`, `file_unique_id`,
  `file_name`, `mime_type`, `file_size`, `caption`, and whether the name is
  Telegram-provided or generated.
- Preserve forwarded authorship behavior and existing filters:
  `--forwarded-only`, `--include-plain`, `--since`, `--limit`, `--peek`, and
  `--ack`.

Acceptance criteria:

- `agentgram inbox --format json` and `--format jsonl` include attachments for
  file-bearing messages.
- Markdown and compact output still render readable placeholders and do not
  leak raw `file_id` unless the user chooses JSON/JSONL.
- Plain text-only inbox outputs are byte-for-byte stable where practical, or
  intentionally changed only for documented attachment improvements.

Tests/checks:

- Unit tests for each supported media type.
- Regression tests for existing forwarded/plain filters.
- Regression tests for existing compact, markdown, json, and jsonl outputs.
- Run `python3 -m unittest discover -s tests -v`.
- Run `git diff --check`.
- Run `codex exec review --uncommitted`.

Suggested commit message:

`feat: expose telegram inbox attachment metadata`

### Task 3: Add Inbox File Download Workflow

Scope:

- Add `agentgram inbox --download-files`.
- Add `--download-dir PATH`, defaulting to a private temp/export directory when
  omitted.
- Add `--max-file-bytes BYTES`, defaulting to the public Bot API download limit.
- Download attachments found in rendered inbox records and attach local download
  receipts to the output.
- Preserve consume safety: with `--ack`, acknowledge only after inbox rendering
  and all requested downloads succeed. If any requested download fails, do not
  acknowledge the fetched updates.
- Print concise receipts with local paths, byte counts, sha256 values, and safe
  read/delete hints. Do not print Telegram file URLs or bot tokens.

Acceptance criteria:

- A user can send or forward a file to the Agentgram bot, then an agent can run:

  ```sh
  agentgram inbox --include-plain --download-files --download-dir /tmp --ack
  ```

  and receive a local path suitable for inspection.

- If multiple files are present, the receipt clearly lists all downloaded files.
- Oversized files fail with an actionable message and do not ack updates.
- Existing `agentgram inbox` behavior without `--download-files` remains
  unchanged.

Tests/checks:

- Unit tests for successful download, multiple attachments, ack-after-download,
  no-ack-on-download-failure, oversized refusal, no-overwrite, and receipt
  output.
- CLI smoke test: `PYTHONDONTWRITEBYTECODE=1 bin/agentgram inbox --help`.
- Run `python3 -m unittest discover -s tests -v`.
- Run `git diff --check`.
- Run `codex exec review --uncommitted`.

Suggested commit message:

`feat: download telegram inbox attachments`

### Task 4: Add Direct File Download Command

Scope:

- Add `agentgram download-file <file_id> --output PATH`.
- Support output as either a directory or an explicit file path.
- Support optional `--filename NAME` for safe caller-provided naming.
- Support optional `--max-file-bytes BYTES`.
- Keep this command lower priority than `inbox --download-files`; it exists for
  cases where an agent already has a `file_id` from JSON/JSONL output.

Acceptance criteria:

- Agents can download a specific file from a known `file_id` without refetching
  the inbox.
- The command follows the same token-redaction, no-overwrite, private-file, and
  size-limit rules as the inbox download workflow.
- The command prints a concise receipt with path, bytes, sha256, and safe read
  hint.

Tests/checks:

- Unit tests for directory output, explicit path output, filename override,
  missing file path from Telegram, oversized refusal, and redacted errors.
- CLI smoke test: `PYTHONDONTWRITEBYTECODE=1 bin/agentgram download-file --help`.
- Run `python3 -m unittest discover -s tests -v`.
- Run `git diff --check`.
- Run `codex exec review --uncommitted`.

Suggested commit message:

`feat: add direct telegram file download command`

### Task 5: Update Agent Instructions, Plugin Mirror, And Docs

Scope:

- Update root README and plugin README with file-download examples, limits, and
  safe phrasing for users.
- Update root skill and plugin skill so agents know how to respond to requests
  like "download the file I just sent to the Agentgram bot and read it".
- Explain that users must send or forward the file to the Agentgram bot, not to
  their personal saved messages.
- Document public Bot API 20 MB download behavior and mention local Bot API
  server support as the future path for larger files without implementing it.
- Keep root and plugin copies synchronized.

Acceptance criteria:

- Docs include the recommended agent command:

  ```sh
  agentgram inbox --include-plain --download-files --download-dir /tmp --ack
  ```

- Docs include the direct fallback:

  ```sh
  agentgram download-file <file_id> --output /tmp
  ```

- Skill instructions preserve the rule that Agentgram sends/downloads are
  explicit and user-requested.

Tests/checks:

- Run `python3 -m unittest discover -s tests -v`.
- Run `python3 scripts/validate_manifest.py`.
- Run plugin validation commands already used by the repo, if present.
- Run `git diff --check`.
- Run `codex exec review --uncommitted`.

Suggested commit message:

`docs: document agentgram file downloads`

### Task 6: End-To-End Validation And Release Readiness

Scope:

- Run the full local test and validation suite.
- Perform a non-destructive CLI help smoke test for every affected command.
- If a small safe test file is available in Telegram pending updates, perform a
  live manual smoke test only with explicit user approval. Otherwise document
  that live Telegram download was not exercised.
- Verify plugin packaging still includes the updated CLI/docs/skill files.
- Produce the final PR-ready summary and residual-risk note.

Acceptance criteria:

- Full tests pass.
- Manifest/plugin validation passes.
- `codex exec review --uncommitted` is clean after fixes.
- PR body includes exact checks and notes any live Telegram smoke test that was
  skipped.

Tests/checks:

- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- Plugin validation root and `plugins/agentgram`, matching existing repo
  commands.
- `PYTHONDONTWRITEBYTECODE=1 bin/agentgram inbox --help`
- `PYTHONDONTWRITEBYTECODE=1 bin/agentgram download-file --help`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

`chore: validate telegram file download workflow`
