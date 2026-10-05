#!/usr/bin/env python3
"""Собирает основной self-host артефакт p2pKanban без сторонних Python-пакетов."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
OUTPUT_DIR = ROOT / "release" / "dist"

ROOT_FILES = (
    ".dockerignore",
    ".gitattributes",
    ".gitignore",
    "README.md",
    "VERSION",
    "bootstrap.py",
)
SOURCE_DIRS = (
    "backend",
    "frontend",
    "deploy/bootstrap",
)
TOOL_FILES = (
    "tools/container_bootstrap.py",
    "tools/resilient_bootstrap.py",
    "tools/update_control_plane.py",
)
EXCLUDED_PARTS = {
    ".git",
    ".dev-bootstrap",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "coverage",
    "dist",
    "node_modules",
    "playwright-report",
    "target",
    "test-results",
}
EXCLUDED_SUFFIXES = {
    ".db",
    ".env",
    ".exe",
    ".log",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".tsbuildinfo",
}


class ReleaseBuildError(RuntimeError):
    """Ожидаемая ошибка подготовки релизного архива."""


def read_version() -> str:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ReleaseBuildError(f"Не удалось прочитать VERSION: {exc}") from exc
    if not version or any(char.isspace() for char in version):
        raise ReleaseBuildError("VERSION пуст или содержит пробелы.")
    return version


def git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def public_github_repository(remote: str | None) -> str | None:
    if not remote:
        return None
    ssh = re.fullmatch(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?", remote)
    if ssh:
        return f"https://github.com/{ssh.group(1)}/{ssh.group(2)}"
    https = re.fullmatch(
        r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?",
        remote,
    )
    if https:
        return f"https://github.com/{https.group(1)}/{https.group(2)}"
    return None


def check_git(version: str, *, require_tag: bool, allow_dirty: bool) -> str | None:
    commit = git_output("rev-parse", "HEAD")
    if commit is None:
        if require_tag:
            raise ReleaseBuildError(
                "Нельзя проверить тег: архив запущен вне Git-репозитория."
            )
        return None

    dirty = git_output("status", "--porcelain")
    if dirty and not allow_dirty:
        raise ReleaseBuildError(
            "Рабочее дерево содержит изменения. Зафиксируйте их или передайте "
            "--allow-dirty для локальной пробной сборки."
        )

    if require_tag:
        tag = git_output("describe", "--tags", "--exact-match")
        expected = f"v{version}"
        if tag != expected:
            raise ReleaseBuildError(
                f"Текущий commit должен иметь тег {expected}, найдено: {tag or 'без тега'}."
            )
    return commit


def is_excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return True
    if path.name == ".env" or path.name.startswith(".env."):
        return True
    return path.suffix.lower() in EXCLUDED_SUFFIXES


def iter_source_files() -> Iterable[Path]:
    seen: set[Path] = set()
    for relative in ROOT_FILES + TOOL_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise ReleaseBuildError(f"Обязательный файл отсутствует: {relative}")
        seen.add(path)
        yield path

    for relative in SOURCE_DIRS:
        directory = ROOT / relative
        if not directory.is_dir():
            raise ReleaseBuildError(f"Обязательный каталог отсутствует: {relative}")
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not is_excluded(path) and path not in seen:
                seen.add(path)
                yield path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_write_bytes(
    archive: zipfile.ZipFile,
    name: str,
    payload: bytes,
    *,
    executable: bool = False,
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = ((0o100755 if executable else 0o100644) << 16)
    archive.writestr(info, payload)


def zip_write_file(
    archive: zipfile.ZipFile,
    source: Path,
    name: str,
) -> None:
    executable = os.access(source, os.X_OK) or source.suffix == ".sh"
    zip_write_bytes(archive, name, source.read_bytes(), executable=executable)


def release_readme(version: str, language: str) -> bytes:
    filename = (
        "README_RELEASE_RU.md" if language == "ru" else "README_RELEASE_EN.md"
    )
    template = ROOT / "release" / f"p2pkanban-v{version}" / filename
    if not template.is_file():
        raise ReleaseBuildError(f"Отсутствует релизная памятка: {template}")
    return template.read_bytes()


def build(*, require_tag: bool, allow_dirty: bool) -> tuple[Path, Path]:
    version = read_version()
    commit = check_git(version, require_tag=require_tag, allow_dirty=allow_dirty)
    source_files = list(iter_source_files())
    prefix = f"p2pkanban-v{version}-bootstrap"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = OUTPUT_DIR / f"{prefix}.zip"
    checksum_path = OUTPUT_DIR / "SHA256SUMS.txt"

    build_info = {
        "product": "p2pKanban",
        "version": version,
        "gitCommit": commit,
        "gitRepository": public_github_repository(
            git_output("remote", "get-url", "origin")
        ),
        "updateBranch": "main",
        "runtime": "Docker Compose v2",
        "entrypoint": "python bootstrap.py",
        "updateEntrypoint": "python bootstrap.py update",
    }

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source in source_files:
            relative = source.relative_to(ROOT).as_posix()
            zip_write_file(archive, source, f"{prefix}/{relative}")
        zip_write_bytes(
            archive,
            f"{prefix}/BUILD_INFO.json",
            (json.dumps(build_info, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            ),
        )
        zip_write_bytes(
            archive,
            f"{prefix}/README_RELEASE_RU.md",
            release_readme(version, "ru"),
        )
        zip_write_bytes(
            archive,
            f"{prefix}/README_RELEASE_EN.md",
            release_readme(version, "en"),
        )

    checksum_path.write_text(
        f"{sha256(archive_path)}  {archive_path.name}\n",
        encoding="utf-8",
    )
    return archive_path, checksum_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собрать self-host ZIP p2pKanban и SHA256SUMS.txt."
    )
    parser.add_argument(
        "--require-tag",
        action="store_true",
        help="требовать, чтобы HEAD имел точный тег v<VERSION>",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="разрешить пробную сборку из незакоммиченного дерева",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    try:
        archive_path, checksum_path = build(
            require_tag=args.require_tag,
            allow_dirty=args.allow_dirty,
        )
    except ReleaseBuildError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    print(f"Архив: {archive_path}")
    print(f"Контрольная сумма: {checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
