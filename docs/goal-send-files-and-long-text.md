# Agentgram File Sending and Long Text Delivery

Implement the plan task by task. Each task must be developed, reviewed, opened
as its own pull request, merged, and verified before moving on, unless tasks are
explicitly safe to run in parallel.

Agentgram should let Codex and other local AI agents send explicit,
user-requested Telegram files as well as text. Agents should be able to choose
the right behavior when a user asks to send a file, report, log, diff, or long
message. This goal touches the Agentgram CLI, Telegram client, tests, docs,
Codex skill instructions, packaged plugin mirror, release metadata, and
follow-up public marketplace/curated-list sync. It excludes hosted services,
automatic unsolicited notifications, media-specific commands such as
`send-photo`, and files larger than Telegram Bot API limits.

Verified planning assumptions:

- Telegram `sendMessage` text is limited to 1-4096 characters after entity
  parsing.
- Telegram `sendDocument` accepts general files via multipart upload, currently
  up to 50 MB for bot uploads.
- Telegram document captions are limited to 0-1024 characters after entity
  parsing.

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

### Task 1: Add Telegram Document Upload Support

Scope:

- Add standard-library multipart/form-data support to `TelegramClient`.
- Add `send_document` around Telegram `sendDocument`.
- Validate local file paths before upload:
  - path must exist
  - path must be a regular file
  - path must be readable
  - file size must be greater than 0 and at most 50 MB
- Validate captions with the same visible-text semantics as messages, but with a
  1024-character limit after entity parsing.
- Do not print or log bot tokens, file contents, or secret env values.

Acceptance criteria:

- A local file can be sent to the configured chat using Telegram `sendDocument`.
- Telegram API errors are surfaced through existing redacted error handling.
- Oversized files fail locally before upload.
- Missing, directory, unreadable, and empty file cases fail with clear
  user-correctable CLI errors.
- Existing `send`, `chat-id`, `doctor`, and `update` behavior is unchanged.

Tests/checks:

- Unit tests for multipart request construction without real network calls.
- Unit tests for file validation edge cases.
- Unit tests for caption length validation with plain text, HTML, and
  MarkdownV2.
- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
feat: add telegram document upload support
```

### Task 2: Add `agentgram send-file`

Scope:

- Add a public CLI command:

  ```sh
  agentgram send-file [--chat-id <id>] [--caption <text>] [--parse-mode HTML|MarkdownV2] [--silent] <path>
  ```

- Use `TELEGRAM_CHAT_ID` by default and `--chat-id` as a one-off override.
- Return output consistent with `send`, for example
  `sent document message_id=<id>`.
- Keep command behavior deterministic and safe for agents:
  - no glob expansion inside Agentgram
  - no implicit directory archiving
  - no reading file content into logs
  - no automatic sending unless a user explicitly asks

Acceptance criteria:

- `agentgram send-file ./report.md --caption "Report"` calls `sendDocument`
  with the correct chat id, file, caption, parse mode, and silent flag.
- The CLI help lists `send-file`.
- Failure modes produce no traceback and do not leak secrets.

Tests/checks:

- CLI unit tests for successful `send-file`.
- CLI unit tests for missing token, missing chat id, invalid file path, and
  malformed token.
- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
feat: add send-file command
```

### Task 3: Add Long Text Delivery Modes

Scope:

- Preserve the current default: plain `agentgram send` rejects text above 4096
  visible characters.
- Add explicit long-text modes:

  ```sh
  agentgram send --split "long text..."
  agentgram send --as-file "long text..."
  agentgram send --as-file --filename report.md "long text..."
  ```

- `--split` sends multiple messages, each within Telegram's 4096-character
  visible-text limit. Prefer splitting on paragraph or line boundaries, then on
  spaces, and only split mid-word as a last resort.
- Prefix split chunks with stable counters such as `[1/3]`, while keeping each
  final message within the limit.
- `--as-file` writes the text to a temporary UTF-8 file and sends it with
  `sendDocument`. Use a safe default filename such as `agentgram-message.txt`
  when `--filename` is not provided.
- Avoid `--split` with formatted `--parse-mode` initially unless entity-safe
  splitting is implemented. If formatting is not supported for split mode,
  reject that combination with a clear error.

Acceptance criteria:

- Short messages still use one `sendMessage`.
- Over-limit messages still fail by default.
- `--split` sends all chunks in order and reports the message ids or count.
- `--as-file` sends long text as a document without leaving tracked or durable
  temp files.
- No chunk exceeds Telegram's text limit after adding counters.

Tests/checks:

- Unit tests for the splitter boundaries and counter sizing.
- CLI tests for default rejection, split mode, and file mode.
- Tests that split mode rejects unsupported formatted text if not implemented.
- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
feat: support long telegram messages
```

### Task 4: Update Agent Instructions, Docs, and Plugin Mirrors

Scope:

- Update `skills/agentgram/SKILL.md` so agents understand:
  - use `send` for explicit short text messages
  - use `send-file` when the user asks to send a file, report, log, diff,
    archive, or generated artifact
  - use `send --split` or `send --as-file` only when the user asks to send long
    text or the message exceeds Telegram limits
  - never send files automatically just because a task completed
  - confirm ambiguous file paths before sending when the target is unclear
- Update `README.md` with examples and constraints.
- Update `docs/release-checklist.md` with manual smoke tests for `send-file`,
  split messages, and as-file mode.
- Sync the packaged plugin mirror under `plugins/agentgram`.
- Update manifest descriptions/keywords only if needed.

Acceptance criteria:

- An agent reading the skill can correctly choose file sending when a user says
  "send me this file".
- README documents Telegram limits and the command examples.
- Packaged plugin mirror matches the root plugin files needed for marketplace
  installs.

Tests/checks:

- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `python3 /root/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /root/agentgram`
- `python3 /root/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /root/agentgram/plugins/agentgram`
- `git diff --check`
- `codex exec review --uncommitted`

Suggested commit message:

```text
docs: teach agents to send files and long text
```

### Task 5: Release and Public Marketplace Sync

Scope:

- Bump Agentgram version after implementation tasks are merged.
- Run package build and installed-wheel smoke tests.
- Tag a new release.
- If PyPI Trusted Publisher is configured, verify PyPI publish succeeds.
- Upgrade the local Agentgram install and verify `agentgram --version`.
- Sync the curated `awesome-codex-plugins` mirror after the release so the
  public curated marketplace includes `send-file`, long-text support, `bin/`,
  and `src/`.
- If Codex Marketplace submission is approved before this task, verify the
  marketplace listing reflects the new release after source sync.

Acceptance criteria:

- New release is tagged and public.
- Main CI is green.
- Local Agentgram install runs the new version.
- Public install path from the Agentgram repo works:

  ```sh
  codex plugin marketplace add jerryfane/agentgram --ref main
  codex plugin add agentgram@agentgram
  ```

- Curated Awesome Codex Plugins listing is updated or a follow-up PR is opened.

Tests/checks:

- `python3 -m unittest discover -s tests -v`
- `python3 scripts/validate_manifest.py`
- `python3 -m build`
- Installed-wheel smoke: `agentgram --version`, `agentgram --help`,
  `agentgram doctor` with test env unset.
- Fresh Codex marketplace install smoke with a temporary `CODEX_HOME`.
- `codex exec review --uncommitted`

Suggested commit message:

```text
chore: release agentgram file sending support
```
