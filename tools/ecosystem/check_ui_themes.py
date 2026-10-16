#!/usr/bin/env python3
"""Проверка словаря тем интерфейса docs/ecosystem/ui-themes.json.

Только стандартная библиотека.

    python -B tools/ecosystem/check_ui_themes.py               # словарь полон, контрасты в норме
    python -B tools/ecosystem/check_ui_themes.py --directions  # и отчёт о копиях в направлениях
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DICTIONARY = ROOT / "docs/ecosystem/ui-themes.json"
HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
RGBA_RE = re.compile(r"^rgba\(\d{1,3}, \d{1,3}, \d{1,3}, (0|1|0?\.\d+)\)$")
SURFACES = ("background", "surface", "surfaceMuted", "surfaceRaised")
READABLE = ("text", "textMuted", "accentText", "dangerText", "successText", "warningText")
MIN_CONTRAST = 4.5


def luminance(value: str) -> float:
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def check(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("dictionary") != "p2p-kanban-ui-themes/1":
        errors.append("dictionary должен быть p2p-kanban-ui-themes/1")
    tokens = data.get("tokens")
    themes = data.get("themes")
    if not isinstance(tokens, dict) or not tokens:
        return errors + ["tokens должен быть непустым объектом"]
    if not isinstance(themes, list) or not themes:
        return errors + ["themes должен быть непустым массивом"]
    ids = [theme.get("id") for theme in themes]
    if len(set(ids)) != len(ids):
        errors.append("id тем повторяются")
    if data.get("defaultTheme") not in ids:
        errors.append("defaultTheme не найден среди тем")
    for theme in themes:
        name = theme.get("id")
        if theme.get("scheme") not in ("light", "dark"):
            errors.append(f"{name}: scheme должен быть light или dark")
        if not theme.get("label"):
            errors.append(f"{name}: нет label")
        colors = theme.get("colors") or {}
        missing = sorted(set(tokens) - set(colors))
        extra = sorted(set(colors) - set(tokens))
        if missing:
            errors.append(f"{name}: нет токенов {', '.join(missing)}")
        if extra:
            errors.append(f"{name}: лишние токены {', '.join(extra)}")
        for token, value in colors.items():
            if token == "overlay":
                if not RGBA_RE.match(value):
                    errors.append(f"{name}.overlay: ожидается rgba(r, g, b, a)")
            elif not HEX_RE.match(value):
                errors.append(f"{name}.{token}: ожидается #rrggbb в нижнем регистре")
        if missing or any(not HEX_RE.match(colors.get(t, "")) for t in (*SURFACES, *READABLE, "onAccent", "accentStrong")):
            continue
        for surface in SURFACES:
            for token in READABLE:
                ratio = contrast(colors[token], colors[surface])
                if ratio < MIN_CONTRAST:
                    errors.append(f"{name}: {token} на {surface} = {ratio:.2f} < {MIN_CONTRAST}")
        ratio = contrast(colors["onAccent"], colors["accentStrong"])
        if ratio < MIN_CONTRAST:
            errors.append(f"{name}: onAccent на accentStrong = {ratio:.2f} < {MIN_CONTRAST}")
    return errors


def report_directions(data: dict) -> None:
    for direction, relative in sorted((data.get("implementations") or {}).items()):
        path = ROOT / relative
        if not path.is_file():
            print(f"  {direction}: копии {relative} нет")
            continue
        source = path.read_text(encoding="utf-8").lower()
        absent = sorted({
            value for theme in data["themes"] for value in theme["colors"].values()
            if value.startswith("#") and value not in source
        })
        state = "совпадает со словарём" if not absent else f"нет значений: {', '.join(absent)}"
        print(f"  {direction}: {relative} — {state}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directions", action="store_true", help="сообщить, как копии направлений расходятся со словарём")
    args = parser.parse_args()
    data = json.loads(DICTIONARY.read_text(encoding="utf-8"))
    errors = check(data)
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print(f"OK: {len(data['themes'])} темы, {len(data['tokens'])} токенов, контрасты не ниже {MIN_CONTRAST}")
    if args.directions:
        report_directions(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
