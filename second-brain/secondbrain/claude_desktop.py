"""Connect the Claude desktop app to this brain (its MCP server), so Claude can use it on your subscription.

Writes a ``second-brain`` entry into Claude Desktop's ``claude_desktop_config.json``, keeping every other
setting and saving a backup first. Restart Claude Desktop afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "second-brain"


def config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Claude" / "claude_desktop_config.json"


def server_entry(brain_config: Path | None) -> dict[str, Any]:
    # The exact Python that runs this app (e.g. the .venv the Start script made), so Claude finds the brain.
    args = ["-m", "secondbrain"] + (["--config", str(brain_config)] if brain_config else []) + ["mcp"]
    return {"command": sys.executable, "args": args}


def status(path: Path | None = None) -> dict[str, Any]:
    path = path or config_path()
    connected = False
    if path.is_file():
        try:
            connected = SERVER_NAME in json.loads(path.read_text(encoding="utf-8") or "{}").get("mcpServers", {})
        except (ValueError, AttributeError):
            pass
    return {"config_path": str(path), "app_found": path.parent.is_dir(), "connected": connected}


def connect(brain_config: Path | None, path: Path | None = None) -> dict[str, Any]:
    path = path or config_path()
    data: dict[str, Any] = {}
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"Claude Desktop's settings file isn't valid JSON, so it was left alone: {path}") from exc
        shutil.copy2(path, path.with_suffix(".json.bak"))
    data.setdefault("mcpServers", {})[SERVER_NAME] = server_entry(brain_config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {**status(path), "restart_needed": True}
