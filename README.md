# Agentgram

Agentgram is an agent-neutral Telegram messaging plugin. The intended first
release lets Codex and other coding agents send explicit, user-requested
Telegram messages through a bot token and chat id.

This repository currently contains the initial plugin scaffold and implementation
goal. See [GOAL.md](GOAL.md) for the task-by-task plan.

## Planned Interface

```sh
agentgram send "message text"
agentgram chat-id
agentgram doctor
agentgram update
```

The first implementation should use `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID`, avoid storing secrets in repo files, and call Telegram's
official Bot API directly.

## Status

Pre-release scaffold. The send command is not implemented yet.
