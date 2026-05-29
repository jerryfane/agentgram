---
name: agentgram
description: Send explicit, user-requested Telegram messages from an agent session through the local Agentgram command-line tool.
---

# Agentgram

Agentgram is planned as a small Telegram messaging helper for agents. Use this
skill when the user asks to send a Telegram message, verify Telegram messaging
setup, find a chat id, or update the local Agentgram install.

This repository is currently a pre-release scaffold. Before sending messages,
check whether the `agentgram` command exists and whether `agentgram doctor`
passes. If the command is missing, tell the user the implementation is not
installed yet instead of attempting an ad hoc Telegram API call.

Expected future commands:

```sh
agentgram send "message text"
agentgram chat-id
agentgram doctor
agentgram update
```

Secrets must come from environment variables or a user-owned local config file,
never from tracked repository files.
