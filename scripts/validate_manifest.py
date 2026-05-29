#!/usr/bin/env python3
"""Validate Agentgram release metadata without external dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    if not manifest_path.is_file():
        errors.append("missing .codex-plugin/plugin.json")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid .codex-plugin/plugin.json: {exc}")
        else:
            if manifest.get("name") != "agentgram":
                errors.append("plugin name must be agentgram")
            if manifest.get("skills") != "./skills/":
                errors.append("plugin skills path must be ./skills/")
            if not manifest.get("version"):
                errors.append("plugin version is required")
            if not manifest.get("interface", {}).get("defaultPrompt"):
                errors.append("plugin interface.defaultPrompt is required")

    skill_files = sorted((ROOT / "skills").glob("**/SKILL.md"))
    if skill_files != [ROOT / "skills" / "agentgram" / "SKILL.md"]:
        errors.append("expected exactly skills/agentgram/SKILL.md")

    env_example = ROOT / ".env.example"
    if not env_example.is_file():
        errors.append("missing .env.example")
    else:
        env_lines = [
            line.strip()
            for line in env_example.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if env_lines != ["TELEGRAM_BOT_TOKEN=", "TELEGRAM_CHAT_ID="]:
            errors.append(".env.example must contain only empty Telegram variable names")

    for path in (ROOT / "README.md", ROOT / "skills" / "agentgram" / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        if "TELEGRAM_BOT_TOKEN" not in text or "TELEGRAM_CHAT_ID" not in text:
            errors.append(f"{path.relative_to(ROOT)} must document Telegram env vars")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("manifest checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
