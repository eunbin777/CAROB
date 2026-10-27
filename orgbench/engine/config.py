"""Configuration loading.

Config is kept as plain dicts (loaded from YAML) for simplicity. Path values
under the ``paths:`` block are stored relative to the orgbench base directory
(the parent of ``config/``) and resolved via :func:`base_dir`, so the pipeline
runs regardless of the current working directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

__all__ = ["load_yaml", "load_config", "base_dir", "resolve_path"]


def load_yaml(path: str | Path) -> dict | list:
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(path: str | Path = "config/default.yaml") -> dict:
    cfg = load_yaml(path)
    if not isinstance(cfg, dict):
        raise ValueError(f"config must be a mapping: {path}")
    cfg["_config_path"] = str(Path(path).resolve())
    return cfg


def base_dir(config_path: str | Path) -> Path:
    """Base dir = the parent of the ``config/`` directory holding the file."""
    return Path(config_path).resolve().parent.parent


def resolve_path(cfg: dict, key: str) -> Path:
    """Resolve a ``paths.<key>`` entry against the orgbench base directory."""
    return base_dir(cfg["_config_path"]) / cfg["paths"][key]
