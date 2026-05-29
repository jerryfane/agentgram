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
    manifest: dict[str, object] = {}
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
            if manifest.get("version") != "0.1.0":
                errors.append("plugin version must match the v0.1.0 release")

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

    marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_path.is_file():
        errors.append("missing .agents/plugins/marketplace.json")
    else:
        try:
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid .agents/plugins/marketplace.json: {exc}")
        else:
            if marketplace.get("name") != "agentgram":
                errors.append("marketplace name must be agentgram")
            plugins = marketplace.get("plugins")
            if not isinstance(plugins, list) or len(plugins) != 1:
                errors.append("marketplace must expose exactly one plugin")
            else:
                plugin = plugins[0]
                if not isinstance(plugin, dict):
                    errors.append("marketplace plugin entry must be an object")
                else:
                    if plugin.get("name") != "agentgram":
                        errors.append("marketplace plugin name must be agentgram")
                    source = plugin.get("source")
                    if not isinstance(source, dict):
                        errors.append("marketplace source must be an object")
                    else:
                        if source.get("source") != "local":
                            errors.append("marketplace source must be local")
                        if source.get("path") != "./plugins/agentgram":
                            errors.append("marketplace source path must point at ./plugins/agentgram")
                    policy = plugin.get("policy")
                    if not isinstance(policy, dict):
                        errors.append("marketplace policy must be present")
                    else:
                        if policy.get("installation") != "AVAILABLE":
                            errors.append("marketplace installation policy must be AVAILABLE")
                        if policy.get("authentication") != "ON_INSTALL":
                            errors.append("marketplace authentication policy must be ON_INSTALL")
                    if plugin.get("category") != "Productivity":
                        errors.append("marketplace category must be Productivity")

    packaged_root = ROOT / "plugins" / "agentgram"
    packaged_files = [
        ".codex-plugin/plugin.json",
        "LICENSE",
        "README.md",
        "bin/agentgram",
        "src/agentgram/__init__.py",
        "src/agentgram/cli.py",
        "src/agentgram/telegram.py",
        "skills/agentgram/SKILL.md",
    ]
    for relative in packaged_files:
        root_file = ROOT / relative
        packaged_file = packaged_root / relative
        if not packaged_file.is_file():
            errors.append(f"missing packaged plugin file plugins/agentgram/{relative}")
        elif root_file.read_text(encoding="utf-8") != packaged_file.read_text(encoding="utf-8"):
            errors.append(f"packaged plugin file plugins/agentgram/{relative} is out of sync")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("manifest checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
