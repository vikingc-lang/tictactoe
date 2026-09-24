"""Configuration loading.

The brain is configured by a TOML file (see ``brain.example.toml``). Lookup order:
``$BRAIN_CONFIG`` -> ``./brain.toml`` -> ``~/.secondbrain/brain.toml``.
String values may reference environment variables as ``${NAME}`` so secrets
(API tokens) never have to live in the file itself.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_HOME = Path(os.environ.get("BRAIN_HOME", "~/.secondbrain")).expanduser()

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` references with environment values."""
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


@dataclass
class SourceConfig:
    name: str
    type: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrainConfig:
    data_dir: Path = DEFAULT_HOME
    output_dir: Path = DEFAULT_HOME / "outputs"
    model: str = "claude-opus-5"
    effort: str = "high"
    learn_from_outputs: bool = True
    auto_enrich: bool = False
    watch_interval: int = 60
    deck_template: Path | None = None   # your firm's branded .pptx to build decks on
    doc_template: Path | None = None    # branded .docx to build documents on
    sources: list[SourceConfig] = field(default_factory=list)
    config_path: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "brain.db"

    def all_sources(self) -> list[SourceConfig]:
        """Configured sources plus the brain's own output folder (so it learns from what it creates)."""
        sources = list(self.sources)
        if self.learn_from_outputs and not any(s.name == "_outputs" for s in sources):
            sources.append(SourceConfig("_outputs", "folder", {"path": str(self.output_dir)}))
        return sources


def find_config_path(explicit: str | None = None) -> Path | None:
    candidates = [explicit, os.environ.get("BRAIN_CONFIG"), "brain.toml", str(DEFAULT_HOME / "brain.toml")]
    for c in candidates:
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser().resolve()
    return None


SECRETS_FILE = "secrets.env"


def load_secrets(data_dir: Path) -> None:
    """Load KEY=VALUE lines from ``<data_dir>/secrets.env`` into the environment (without overriding)."""
    path = data_dir / SECRETS_FILE
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def save_secret(data_dir: Path, key: str, value: str) -> None:
    """Store a secret in ``<data_dir>/secrets.env`` (owner-only permissions) and apply it now."""
    path = data_dir / SECRETS_FILE
    entries: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                entries[k.strip()] = v.strip()
    entries[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in entries.items()), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    os.environ[key] = value


def load_config(explicit: str | None = None) -> BrainConfig:
    path = find_config_path(explicit)
    if path is None:
        cfg = BrainConfig()
    else:
        with open(path, "rb") as fh:
            raw = expand_env(tomllib.load(fh))
        brain = raw.get("brain", {})
        data_dir = Path(brain.get("data_dir", DEFAULT_HOME)).expanduser()
        cfg = BrainConfig(
            data_dir=data_dir,
            output_dir=Path(brain.get("output_dir", data_dir / "outputs")).expanduser(),
            model=brain.get("model", "claude-opus-5"),
            effort=brain.get("effort", "high"),
            learn_from_outputs=brain.get("learn_from_outputs", True),
            auto_enrich=brain.get("auto_enrich", False),
            watch_interval=int(brain.get("watch_interval", 60)),
            deck_template=Path(brain["deck_template"]).expanduser() if brain.get("deck_template") else None,
            doc_template=Path(brain["doc_template"]).expanduser() if brain.get("doc_template") else None,
            config_path=path,
        )
        for s in raw.get("sources", []):
            s = dict(s)
            cfg.sources.append(SourceConfig(name=s.pop("name"), type=s.pop("type"), options=s))
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    load_secrets(cfg.data_dir)
    return cfg


def append_source(config_file: Path, name: str, type_: str, **options: Any) -> None:
    """Append a ``[[sources]]`` block to the config file (creating it if needed)."""
    # json.dumps yields valid TOML strings, including escaped Windows backslashes.
    lines = ["", "[[sources]]", f"name = {json.dumps(name)}", f"type = {json.dumps(type_)}"]
    for key, val in options.items():
        if isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        else:
            lines.append(f"{key} = {json.dumps(val)}")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def remove_source(config_file: Path, name: str) -> bool:
    """Delete the ``[[sources]]`` block with this name. Returns True if one was removed."""
    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)
    blocks: list[list[str]] = [[]]
    for line in lines:
        if line.strip().startswith("["):
            blocks.append([])
        blocks[-1].append(line)
    kept, removed = [], False
    for block in blocks:
        text = "".join(block)
        if text.lstrip().startswith("[[sources]]") and re.search(
                r'^\s*name\s*=\s*"' + re.escape(json.dumps(name)[1:-1]) + r'"\s*$', text, re.M):
            removed = True
            continue
        kept.append(text)
    if removed:
        config_file.write_text("".join(kept), encoding="utf-8")
    return removed
