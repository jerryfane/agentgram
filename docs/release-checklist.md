# Release Checklist

Use this checklist before tagging or announcing an Agentgram release.

## Required Checks

- Confirm the repository is clean with `git status --short`.
- Run `python3 -m unittest discover -s tests -v`.
- Run `python3 scripts/validate_manifest.py`.
- Run `python3 -m build`.
- Install the built wheel in a temporary virtual environment and run
  `agentgram --help`.
- Run `bin/agentgram send --help` and verify it lists `--split`, `--as-file`,
  and `--filename`.
- Run `bin/agentgram send-file --help`.
- Run `git diff --check`.
- Run `bin/agentgram update --check` from the release checkout.
- Verify `.env.example` contains variable names only.
- Verify `.agents/plugins/marketplace.json` points at `./plugins/agentgram`.
- Verify PyPI package metadata uses distribution name `agentgram-tg` and command
  name `agentgram`.
- Verify no Telegram tokens, chat ids, generated plugin packages, logs, caches,
  or local session files are staged.

## Fresh Clone Smoke

```sh
git clone https://github.com/jerryfane/agentgram.git /tmp/agentgram-smoke
cd /tmp/agentgram-smoke
python3 -m unittest discover -s tests -v
python3 scripts/validate_manifest.py
python3 -m pip install --upgrade build
python3 -m build
python3 -m venv /tmp/agentgram-wheel-smoke
/tmp/agentgram-wheel-smoke/bin/python -m pip install dist/*.whl
/tmp/agentgram-wheel-smoke/bin/agentgram --help
/tmp/agentgram-wheel-smoke/bin/agentgram send --help
/tmp/agentgram-wheel-smoke/bin/agentgram send-file --help
bin/agentgram --help
bin/agentgram send --help
bin/agentgram send-file --help
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

## Discovery Smoke

- Confirm GitHub topics include `codex-plugin`, `openai-codex`,
  `telegram-bot`, `ai-agents`, `agent-tools`, `python`, `cli`, and
  `notifications`.
- Confirm the latest release notes mention both Codex install and
  `pipx install agentgram-tg`.
- Submit or refresh the community marketplace listing and awesome-list PR when
  release metadata changes.

## Optional Live Telegram Smoke

Only run this with explicit test credentials from the user:

```sh
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
bin/agentgram doctor
bin/agentgram send "Agentgram release smoke"
tmp_file="$(mktemp /tmp/agentgram-smoke.XXXXXX.txt)"
printf 'Agentgram file smoke\n' > "$tmp_file"
bin/agentgram send-file "$tmp_file" --caption "Agentgram file smoke"
bin/agentgram send --split "$(python3 - <<'PY'
print('Agentgram split smoke ' * 260)
PY
)"
bin/agentgram send --as-file --filename agentgram-smoke.txt "$(python3 - <<'PY'
print('Agentgram as-file smoke ' * 260)
PY
)"
rm -f "$tmp_file"
```
