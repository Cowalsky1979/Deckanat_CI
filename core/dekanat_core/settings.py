"""Загрузка config/settings.yaml, можно переопределить через env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("DEKANAT_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("DEKANAT_DATA_DIR", ROOT / "data"))


@lru_cache(maxsize=1)
def get_settings() -> dict:
    path = Path(os.environ.get("DEKANAT_SETTINGS", CONFIG_DIR / "settings.yaml"))
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def rules_path() -> Path:
    return Path(os.environ.get("DEKANAT_RULES", DATA_DIR / "rules.md"))
