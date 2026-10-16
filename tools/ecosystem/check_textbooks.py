#!/usr/bin/env python3
"""Страж учебников: в docs/textbooks/ нет растра, ссылки живые, скриншоты описаны.

Только стандартная библиотека. Ничего не пишет и сеть не трогает. Правила —
раздел 6 docs/ecosystem/textbooks.md:

- растровых файлов (.png, .jpg, .jpeg, .gif, .webp, .bmp) в каталоге нет;
- в SVG не встроен растр (<image> с data: или внешней ссылкой), SVG не тяжелее 300 КиБ;
- относительные ссылки Markdown ведут в существующие файлы;
- картинка в Markdown — файл из репозитория или ассет релиза учебника;
- каждый ассет релиза описан в shots.json, и каждый описанный где-то используется.

    python -B tools/ecosystem/check_textbooks.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
BOOKS = ROOT / "docs" / "textbooks"
SHOTS = BOOKS / "shots.json"
RASTER = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
SVG_MAX_BYTES = 300 * 1024
LINK_RE = re.compile(r"(!?)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
SVG_IMAGE_RE = re.compile(r"<image\b[^>]*\b(?:xlink:)?href\s*=\s*[\"']([^\"']+)[\"']", re.I)
FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)


def load_shots(errors: list[str]) -> tuple[str, set[str]]:
    if not SHOTS.is_file():
        errors.append("docs/textbooks/shots.json не найден")
        return "", set()
    try:
        data = json.loads(SHOTS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"shots.json: не JSON: {exc}")
        return "", set()
    release = data.get("release") or {}
    repo = release.get("repository")
    prefix = release.get("tagPrefix")
    if data.get("formatVersion") != 1 or not isinstance(repo, str) or not isinstance(prefix, str):
        errors.append("shots.json: нужны formatVersion 1, release.repository и release.tagPrefix")
        return "", set()
    base = rf"https://github\.com/{re.escape(repo)}/releases/download/{re.escape(prefix)}\d{{4}}-\d{{2}}/"
    names: set[str] = set()
    shots = data.get("shots")
    if not isinstance(shots, list):
        errors.append("shots.json: shots должен быть массивом")
        return base, names
    for index, shot in enumerate(shots):
        label = f"shots.json: shots[{index}]"
        if not isinstance(shot, dict):
            errors.append(f"{label} не объект")
            continue
        for key in ("file", "direction", "scenario", "theme"):
            if not isinstance(shot.get(key), str) or not shot[key].strip():
                errors.append(f"{label}.{key} должен быть непустой строкой")
        name = shot.get("file")
        if isinstance(name, str):
            if "/" in name or Path(name).suffix.lower() not in RASTER:
                errors.append(f"{label}.file: имя растрового файла без каталога, сейчас {name!r}")
            if name in names:
                errors.append(f"{label}.file повторяется: {name}")
            names.add(name)
    return base, names


def strip_code(text: str) -> str:
    return FENCE_RE.sub("", text)


def check_markdown(path: Path, base: str, used: set[str], errors: list[str]) -> None:
    rel = path.relative_to(ROOT).as_posix()
    text = strip_code(path.read_text(encoding="utf-8"))
    targets = [(bang == "!", target) for bang, target in LINK_RE.findall(text)]
    targets += [(True, src) for src in HTML_IMG_RE.findall(text)]
    for is_image, target in targets:
        if target.startswith("#") or target.startswith("mailto:"):
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            if not is_image:
                continue
            match = re.match(base + r"([^/?#]+)$", target) if base else None
            if not match:
                errors.append(f"{rel}: картинка не из репозитория и не ассет релиза учебника: {target}")
                continue
            name = unquote(match.group(1))
            used.add(name)
            continue
        local = (path.parent / unquote(target.split("#", 1)[0])).resolve()
        if not local.exists():
            errors.append(f"{rel}: битая ссылка {target}")
            continue
        if is_image and local.suffix.lower() in RASTER:
            errors.append(f"{rel}: растровая картинка из репозитория {target}; скриншоты — ассеты релиза")


def check_svg(path: Path, errors: list[str]) -> None:
    rel = path.relative_to(ROOT).as_posix()
    size = path.stat().st_size
    if size > SVG_MAX_BYTES:
        errors.append(f"{rel}: SVG {size // 1024} КиБ, больше {SVG_MAX_BYTES // 1024} КиБ")
    text = path.read_text(encoding="utf-8", errors="replace")
    for href in SVG_IMAGE_RE.findall(text):
        errors.append(f"{rel}: в SVG встроена картинка ({href[:40]}…); растр в учебниках не хранится")


def main() -> int:
    errors: list[str] = []
    if not BOOKS.is_dir():
        print("FAIL: каталога docs/textbooks нет")
        return 1
    base, described = load_shots(errors)
    used: set[str] = set()
    files = sorted(p for p in BOOKS.rglob("*") if p.is_file())
    for path in files:
        suffix = path.suffix.lower()
        if suffix in RASTER:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: растровый файл в docs/textbooks")
        elif suffix == ".svg":
            check_svg(path, errors)
        elif suffix == ".md":
            check_markdown(path, base, used, errors)
    for name in sorted(used - described):
        errors.append(f"скриншот {name} используется, но не описан в shots.json")
    for name in sorted(described - used):
        errors.append(f"скриншот {name} описан в shots.json, но нигде не используется")
    if errors:
        print(f"FAIL: учебники, нарушений {len(errors)}")
        for line in errors:
            print(f"  - {line}")
        return 1
    print(f"OK: учебники, файлов {len(files)}, скриншотов {len(used)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
