#!/usr/bin/env python3
"""Статические проверки релизной подготовки p2pKanban."""

from __future__ import annotations

import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
REQUIRED_FILES = (
    "VERSION",
    "README.md",
    "bootstrap.py",
    "deploy/bootstrap/compose.yaml",
    "docs/product/version-policy.md",
    f"docs/product/v{EXPECTED_VERSION}-release-notes.md",
    f"release/p2pkanban-v{EXPECTED_VERSION}/README_RELEASE_RU.md",
    f"release/p2pkanban-v{EXPECTED_VERSION}/README_RELEASE_EN.md",
)
MARKDOWN_EXCLUDES = {
    Path("release/p2p-planner-v1.0.0-beta.1-web-win64/README_RELEASE.md"),
    Path(f"release/p2pkanban-v{EXPECTED_VERSION}/README_RELEASE_EN.md"),
}
MARKDOWN_EXCLUDED_PARTS = {
    ".git",
    ".dev-bootstrap",
    "node_modules",
    "target",
    "dist",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(relative: str) -> dict:
    with (ROOT / relative).open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        fail(f"{relative}: ожидался JSON object")
    return value


def check_versions() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != "2.1.0":
        fail(f"VERSION={version!r}, для этой линии ожидалось '2.1.0'")
    if version != EXPECTED_VERSION:
        fail(f"VERSION={version!r}, ожидалось {EXPECTED_VERSION!r}")

    cargo = tomllib.loads((ROOT / "backend/Cargo.toml").read_text(encoding="utf-8"))
    if cargo["package"]["version"] != version:
        fail("backend/Cargo.toml не совпадает с VERSION")
    cargo_lock = (ROOT / "backend/Cargo.lock").read_text(encoding="utf-8")
    backend_lock_entry = (
        f'name = "p2p-planner-backend"\nversion = "{version}"'
    )
    if backend_lock_entry not in cargo_lock:
        fail("backend/Cargo.lock не совпадает с VERSION")

    frontend = load_json("frontend/package.json")
    frontend_lock = load_json("frontend/package-lock.json")
    if frontend.get("version") != version:
        fail("frontend/package.json не совпадает с VERSION")
    if frontend_lock.get("version") != version:
        fail("frontend/package-lock.json не совпадает с VERSION")
    if frontend_lock.get("packages", {}).get("", {}).get("version") != version:
        fail("root package в frontend/package-lock.json не совпадает с VERSION")

    openapi = (ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8")
    if "title: p2pKanban Backend API" not in openapi:
        fail("OpenAPI всё ещё использует старое имя продукта")

def strip_markdown_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return text


def check_document_language() -> None:
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*.md")):
        relative = path.relative_to(ROOT)
        if (
            relative in MARKDOWN_EXCLUDES
            or (
                relative.parts
                and relative.parts[0] == "release"
                and relative.name == "README_RELEASE_EN.md"
            )
            or any(part in MARKDOWN_EXCLUDED_PARTS for part in relative.parts)
        ):
            continue
        text = strip_markdown_code(path.read_text(encoding="utf-8", errors="replace"))
        cyrillic = sum("\u0400" <= char <= "\u04ff" for char in text)
        latin = sum("a" <= char.lower() <= "z" for char in text)
        if latin < 120:
            continue
        share = cyrillic / max(cyrillic + latin, 1)
        if share < 0.18:
            failures.append(f"{relative} ({share:.1%} кириллицы)")
    if failures:
        fail(
            "Остались англоязычные Markdown-документы:\n- "
            + "\n- ".join(failures)
        )


def check_release_surface() -> None:
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            fail(f"Отсутствует обязательный релизный файл: {relative}")

    active_docs = (
        (ROOT / "README.md").read_text(encoding="utf-8")
        + (ROOT / "docs/README.md").read_text(encoding="utf-8")
        + (ROOT / "docs/product/v1-execution-roadmap.md").read_text(
            encoding="utf-8"
        )
        + (ROOT / "docs/product/v1-known-limitations.md").read_text(
            encoding="utf-8"
        )
    )
    expected_tag = f"v{EXPECTED_VERSION}"
    if expected_tag not in active_docs:
        fail(f"Активная документация не фиксирует {expected_tag}")

    policy = (ROOT / "docs/product/version-policy.md").read_text(encoding="utf-8")
    if "непрерыв" not in policy.lower():
        fail("Политика версий не фиксирует непрерывную разработку")
    if "stable/dev/beta" not in policy:
        fail("Политика версий не фиксирует отказ от каналов stable/dev/beta")

    release_notes = (ROOT / f"docs/product/v{EXPECTED_VERSION}-release-notes.md").read_text(
        encoding="utf-8"
    )
    if "Windows" not in release_notes or "Android" not in release_notes:
        fail("Release notes v1 не описывают Windows и Android")


def check_bundle_builder() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import build_release_bundle as builder

    files = list(builder.iter_source_files())
    if not files:
        fail("Сборщик не нашёл исходные файлы")
    for path in files:
        relative = path.relative_to(ROOT)
        if any(part in builder.EXCLUDED_PARTS for part in relative.parts):
            fail(f"Сборщик пропускает запрещённый каталог: {relative}")
        if path.name == ".env" or path.name.startswith(".env."):
            fail(f"Сборщик пропускает env-файл: {relative}")

    archive_path, checksum_path = builder.build(
        require_tag=False,
        allow_dirty=True,
    )
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if not any(name.endswith("/bootstrap.py") for name in names):
            fail("В релизном ZIP нет bootstrap.py")
        if not any(name.endswith("/backend/Cargo.toml") for name in names):
            fail("В релизном ZIP нет backend/Cargo.toml")
        if not any(name.endswith("/frontend/package.json") for name in names):
            fail("В релизном ZIP нет frontend/package.json")
        forbidden = [
            name
            for name in names
            if "/node_modules/" in name
            or "/target/" in name
            or "/.git/" in name
            or name.endswith("/.env")
        ]
        if forbidden:
            fail(f"В релизный ZIP попали запрещённые пути: {forbidden[:5]}")
    if archive_path.name not in checksum_path.read_text(encoding="utf-8"):
        fail("SHA256SUMS.txt не содержит имя собранного архива")


def main() -> int:
    try:
        check_versions()
        check_release_surface()
        check_document_language()
        check_bundle_builder()
    except (AssertionError, OSError, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: версия, документация и релизный ZIP согласованы")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
