# Release Checklist

Use this checklist before tagging or announcing an Agentgram release.

## Required Checks

- Confirm the repository is clean with `git status --short`.
- Run `python3 -m unittest discover -s tests -v`.
- Run `python3 scripts/validate_manifest.py`.
- Run `git diff --check`.
- Run `bin/agentgram update --check` from the release checkout.
- Verify `.env.example` contains variable names only.
- Verify `.agents/plugins/marketplace.json` points at `./plugins/agentgram`.
- Verify no Telegram tokens, chat ids, generated plugin packages, logs, caches,
  or local session files are staged.

## Fresh Clone Smoke

```sh
git clone https://github.com/jerryfane/agentgram.git /tmp/agentgram-smoke
cd /tmp/agentgram-smoke
python3 -m unittest discover -s tests -v
python3 scripts/validate_manifest.py
bin/agentgram --help
bin/agentgram doctor
```

`doctor` may fail until `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set; it
should fail clearly without printing secret values.

## Codex Marketplace Smoke

After merging the release, verify Codex can discover the marketplace:

```sh
codex plugin marketplace add jerryfane/agentgram --ref main
codex plugin list
codex plugin add agentgram@agentgram
```

Start a new Codex thread after installing so updated skills are loaded.

## Optional Live Telegram Smoke

Only run this with explicit test credentials from the user:

```sh
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
bin/agentgram doctor
bin/agentgram send "Agentgram release smoke"
```
