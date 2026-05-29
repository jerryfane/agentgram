# Agentgram Telegram Messaging Plugin Goal

Implement Agentgram task by task. Each task must be developed, reviewed, opened
as its own pull request, merged, and verified before moving on, unless tasks are
explicitly safe to run in parallel.

Agentgram is an agent-neutral plugin and command-line helper that lets coding
agents send explicit, user-requested Telegram messages through a Telegram bot
token. The first release should support Codex discovery through a plugin skill
while keeping the core send path usable by any local agent that can run a CLI
command.

## Core Rules

- Work one task at a time in the listed order by default.
- If tasks are independent, have disjoint file ownership, and do not depend on
  each other's results, they may be done in parallel on separate branches.
- Do not start dependent work until the prerequisite task has passed checks,
  passed `codex exec review --uncommitted`, been pushed, opened as a PR, merged,
  and verified on the target branch.
- Do not commit generated data, logs, caches, build artifacts, secrets,
  credentials, session archives, local plugin build output, or large outputs.
- Preserve existing behavior unless the current task explicitly changes it.
- Keep changes clean, scoped, and organized. Avoid broad rewrites.
- Avoid code duplication. When repeated logic appears, extract small reusable
  helpers that match the repository patterns.
- If implementation depends on external APIs, CLIs, generated scripts, env
  vars, config formats, installers, or third-party behavior, verify the real
  contract with local commands and/or official sources before editing.

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
4. Verify PR tooling is available before the first PR:
   - `gh auth status`
   - repo remote resolves to `https://github.com/jerryfane/agentgram.git`
5. Verify official external contracts before implementation:
   - Telegram Bot API: `https://core.telegram.org/bots/api`
   - Codex plugin docs if changing `.codex-plugin/plugin.json`
   - Claude Code plugin docs only if adding Claude packaging

## Product Decisions

- The stable project name is `agentgram`.
- The CLI command is `agentgram`.
- Agentgram sends only when the user explicitly asks; it must not auto-notify on
  every agent completion in the first release.
- The minimal send path uses Telegram Bot API `sendMessage`.
- Required configuration is `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- Tokens must not be printed, logged, committed, or stored in generated files.
- Use Python standard library HTTP by default to avoid a dependency install
  step. Add third-party packages only if a task proves they are worth it.
- Send JSON over HTTPS POST to avoid shell quoting problems and URL length
  limits.
- Default message mode is plain text. Optional parse modes may be added with an
  explicit `--parse-mode HTML|MarkdownV2` flag.
- Respect Telegram's `sendMessage` text limit of 1-4096 characters after entity
  parsing. Fail clearly for over-limit input in the first release; chunking can
  be a later feature.
- Include an `update` command. It should update a git-based local install with
  `git pull --ff-only`, re-run validation, and print any runtime-specific
  reinstall instructions. It must not overwrite local uncommitted changes.

## Public Interface

Add:

```text
agentgram send [--chat-id <id>] [--parse-mode HTML|MarkdownV2] [--silent] [--no-preview] <text>
agentgram chat-id [--raw]
agentgram doctor [--json]
agentgram update [--check] [--repo <path>]
```

Behavior:

- `send` reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` unless `--chat-id` is
  provided. It posts `chat_id`, `text`, and optional flags to Telegram
  `sendMessage`, then prints the sent message id on success.
- `chat-id` calls Telegram `getUpdates`, extracts candidate chat ids from recent
  messages, and prints enough context for the user to choose the right id.
- `doctor` verifies command availability, env var presence without revealing
  secrets, token shape, Telegram `getMe`, optional chat reachability, plugin
  manifest presence, and skill file presence.
- `update --check` reports whether the local git checkout is behind its upstream
  without modifying files.
- `update` refuses dirty worktrees, runs `git pull --ff-only`, validates the CLI
  and plugin files, and prints clear next-step commands for Codex or other
  runtimes.

## Implementation Tasks

### Task 1: Build the Agentgram CLI core

Scope:
- Add an executable `agentgram` Python CLI under `bin/` or `scripts/` with
  subcommands `send`, `chat-id`, `doctor`, and `update`.
- Implement a small Telegram client helper using `urllib.request` and JSON.
- Read token/chat configuration from environment variables only.
- Add input validation for missing env vars, empty text, unsupported parse
  modes, and text longer than Telegram's `sendMessage` limit.

Acceptance criteria:
- `agentgram --help` lists all public commands.
- `agentgram send "hello"` posts through Telegram when valid env vars are set.
- Missing token/chat id errors are clear and do not print secret values.
- Telegram API errors include the Telegram error description without printing
  the bot token.
- `agentgram chat-id` can show recent candidate chat ids from `getUpdates`.

Tests/checks:
- Unit tests for argument parsing, env resolution, request payload construction,
  length validation, and error redaction.
- Mocked HTTP tests for `sendMessage`, `getUpdates`, `getMe`, and Telegram
  error responses.
- `python -m pytest` or the selected standard test command.
- Manual smoke with a real bot token only when the user provides test env vars.

Suggested commit:
- `feat: add agentgram telegram cli`

### Task 2: Package the Codex plugin skill

Scope:
- Replace the scaffold skill with final Agentgram usage guidance.
- Keep `.codex-plugin/plugin.json` aligned with the implemented files.
- Document exact behavior for future agents: use `agentgram doctor`, then
  `agentgram send`, and never bypass the CLI with ad hoc token handling unless
  the user explicitly asks.
- Add install/use docs in `README.md`.

Acceptance criteria:
- Codex can discover the Agentgram skill from the plugin package.
- The skill points to the CLI as the execution path.
- The README shows env setup, chat id discovery, send usage, doctor, and update.
- No docs instruct users to commit tokens or put secrets in tracked files.

Tests/checks:
- Validate `.codex-plugin/plugin.json` with available local validation tooling.
- Verify the skill path exists and includes a single `SKILL.md`.
- Run CLI tests from Task 1 after packaging changes.

Suggested commit:
- `docs: package codex agentgram skill`

### Task 3: Implement update and install ergonomics

Scope:
- Finish `agentgram update` around the actual repository layout.
- Add an install script or documented one-line install path for git-based local
  installs.
- Make `doctor` check whether the local checkout has an origin remote and
  whether the plugin manifest/skill files are present.
- Print Codex reinstall or refresh instructions when a Codex plugin install is
  detected but stale.

Acceptance criteria:
- `agentgram update --check` is read-only and reports current/ahead/behind or
  unknown state.
- `agentgram update` refuses to run on a dirty checkout.
- `agentgram update` uses fast-forward-only git updates.
- The command prints deterministic next steps for Codex users without assuming
  all agents use Codex.

Tests/checks:
- Unit tests using temporary git repositories for clean, dirty, no-remote,
  behind, and already-current states.
- CLI smoke test for `agentgram update --check`.
- `git diff --check`.

Suggested commit:
- `feat: add agentgram update workflow`

### Task 4: Release verification and public docs polish

Scope:
- Add release checklist documentation.
- Add `.env.example` with variable names only.
- Add CI for Python tests and manifest checks.
- Verify a clean install path from a fresh clone.

Acceptance criteria:
- A new user can clone the repository, configure env vars, run `doctor`, discover
  chat id, and send a message.
- CI passes on the default branch.
- README clearly states that sends are explicit and user-requested.
- README includes troubleshooting for "bot was not started", bad token, missing
  chat id, forbidden chat, and Telegram API errors.

Tests/checks:
- Fresh-clone smoke in a temporary directory.
- CI green on the PR.
- Optional live Telegram smoke only with user-provided test credentials.

Suggested commit:
- `chore: add release checks and docs`

## Goal Prompt

```text
Use the Gitmoot goal in GOAL.md for jerryfane/agentgram. Implement the tasks in
order. Start with Task 1 only, create a task branch from the current default
branch, preserve the public interface in the goal, verify Telegram and plugin
contracts from official sources before editing, run focused tests plus
codex exec review --uncommitted, open and merge one PR before moving to the next
task, and do not commit any Telegram tokens or generated local plugin output.
```
