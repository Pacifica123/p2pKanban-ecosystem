"""Настройки лаунчера на этой машине: тема и размер окна.

Это настройка устройства, как тема в web и mobile: через узел не
синхронизируется.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .themes import DEFAULT, THEMES as _THEMES

THEMES = tuple(_THEMES)
DEFAULTS = {"theme": DEFAULT, "window": {"width": 1120, "height": 720}}
MIN_SIZE = (760, 520)
MAX_SIZE = (3840, 2160)


def _clamp_size(value: object) -> dict:
    size = dict(DEFAULTS["window"])
    if isinstance(value, dict):
        for key, low, high in (("width", MIN_SIZE[0], MAX_SIZE[0]), ("height", MIN_SIZE[1], MAX_SIZE[1])):
            number = value.get(key)
            if isinstance(number, int) and not isinstance(number, bool):
                size[key] = max(low, min(high, number))
    return size


def normalize(value: object) -> dict:
    value = value if isinstance(value, dict) else {}
    theme = value.get("theme")
    return {"theme": theme if theme in THEMES else DEFAULTS["theme"], "window": _clamp_size(value.get("window"))}


def load(path: Path) -> dict:
    try:
        return normalize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return normalize({})


def save(path: Path, value: dict) -> dict:
    clean = normalize(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return clean


def merge(current: dict, patch: object) -> dict:
    patch = patch if isinstance(patch, dict) else {}
    merged = dict(current)
    if "theme" in patch:
        merged["theme"] = patch["theme"]
    if "window" in patch:
        merged["window"] = patch["window"]
    return normalize(merged)
