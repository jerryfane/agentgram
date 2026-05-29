# Agentgram

Agentgram is an agent-neutral Telegram messaging helper. It lets Codex and
other local coding agents send explicit, user-requested Telegram messages
through a Telegram bot token and chat id.

Agentgram is intentionally local-first. It does not run a hosted service, and it
does not send automatic completion notifications unless a future task explicitly
adds that behavior.

## Requirements

- Python 3.12 or newer.
- A Telegram bot token from BotFather.
- A Telegram chat where the bot has been started or added.

## Configuration

Set secrets in your shell or agent runtime environment:

```sh
export TELEGRAM_BOT_TOKEN="123456:bot-token"
export TELEGRAM_CHAT_ID="123456789"
```

Do not put real tokens in tracked files. `.env` and `.env.*` are ignored for
local use, but environment variables are the preferred setup.

## Usage

Run the local CLI from a checkout:

```sh
bin/agentgram doctor
bin/agentgram send "deploy finished"
bin/agentgram send --silent --no-preview "quiet update"
bin/agentgram send --parse-mode HTML "<b>deploy finished</b>"
```

To discover a chat id, first send a message to the bot in Telegram, then run:

```sh
bin/agentgram chat-id
```

For raw Telegram `getUpdates` output:

```sh
bin/agentgram chat-id --raw
```

To check whether the local git checkout is current using existing local refs:

```sh
bin/agentgram update --check
```

The full mutating update workflow is planned in [GOAL.md](GOAL.md).

## Codex Plugin

The Codex plugin skill lives in `skills/agentgram/SKILL.md`, with the plugin
manifest at `.codex-plugin/plugin.json`. The skill tells Codex to use the local
`agentgram` CLI as the execution path.

When a user asks an agent to send a Telegram message, the agent should:

1. Run `agentgram doctor`, or `bin/agentgram doctor` only from this repository
   checkout.
2. Run `agentgram send "message"`, or `bin/agentgram send "message"` only from
   this repository checkout, if setup is valid.
3. Avoid direct Telegram API calls unless the user explicitly asks to bypass the
   Agentgram CLI.

## Status

Task 1 CLI core is implemented. Packaging, install ergonomics, and release
polish are tracked in [GOAL.md](GOAL.md).
