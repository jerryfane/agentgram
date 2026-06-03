#!/usr/bin/env python3
"""Validate Agentgram release metadata without external dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.2.1"


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
            if manifest.get("version") != EXPECTED_VERSION:
                errors.append(f"plugin version must match the v{EXPECTED_VERSION} release")
            interface = manifest.get("interface", {})
            if isinstance(interface, dict):
                if interface.get("websiteURL") != "https://github.com/jerryfane/agentgram":
                    errors.append("plugin interface.websiteURL must point at the GitHub repo")
                if interface.get("brandColor") != "#1F8A70":
                    errors.append("plugin interface.brandColor must match Agentgram branding")
                for asset_field in ("composerIcon", "logo"):
                    asset = interface.get(asset_field)
                    if asset != "assets/agentgram-logo.svg":
                        errors.append(f"plugin interface.{asset_field} must point at the Agentgram logo")
                    elif not (ROOT / asset).is_file():
                        errors.append(f"plugin interface.{asset_field} points at a missing file")

    pyproject_path = ROOT / "pyproject.toml"
    if not pyproject_path.is_file():
        errors.append("missing pyproject.toml")
    else:
        try:
            pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"invalid pyproject.toml: {exc}")
        else:
            project = pyproject.get("project", {})
            if not isinstance(project, dict):
                errors.append("pyproject.toml must contain a project table")
            else:
                if project.get("name") != "agentgram-tg":
                    errors.append("PyPI distribution name must be agentgram-tg")
                if project.get("version") != EXPECTED_VERSION:
                    errors.append(f"PyPI distribution version must match {EXPECTED_VERSION}")
                scripts = project.get("scripts")
                if not isinstance(scripts, dict) or scripts.get("agentgram") != "agentgram_tg.cli:main":
                    errors.append("pyproject.toml must expose the agentgram CLI script")

    package_init = ROOT / "src" / "agentgram_tg" / "__init__.py"
    if not package_init.is_file():
        errors.append("missing src/agentgram_tg/__init__.py")
    elif f'__version__ = "{EXPECTED_VERSION}"' not in package_init.read_text(encoding="utf-8"):
        errors.append(f"src/agentgram_tg/__init__.py must define version {EXPECTED_VERSION}")

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

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "Codex Telegram plugin",
        "send Telegram messages from Codex",
        "pipx install agentgram-tg",
    ):
        if phrase not in readme:
            errors.append(f"README.md must include discovery phrase: {phrase}")

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
        "assets/agentgram-logo.svg",
        "bin/agentgram",
        "src/agentgram_tg/__init__.py",
        "src/agentgram_tg/cli.py",
        "src/agentgram_tg/telegram.py",
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
