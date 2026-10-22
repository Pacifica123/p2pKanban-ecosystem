"""Где лаунчер держит свои файлы и где лежит checkout экосистемы."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = Path("p2pkanban") / "launcher"
LAUNCHER_DIR = Path(__file__).resolve().parents[1]


def _home_override() -> Path | None:
    value = os.environ.get("P2PKANBAN_LAUNCHER_HOME")
    return Path(value) if value else None


def config_dir() -> Path:
    """Настройки и реестр установок: то, что нельзя потерять."""
    override = _home_override()
    if override:
        return override / "config"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP


def cache_dir() -> Path:
    """Кеш глобального состояния: можно удалить в любой момент."""
    override = _home_override()
    if override:
        return override / "cache"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP


def data_dir() -> Path:
    """venv с PySide6: большое, но восстановимое install-скриптом."""
    override = _home_override()
    if override:
        return override / "data"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP / "data"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP


def registry_file() -> Path:
    """Реестр установок и настройки направлений (p2p-kanban-launcher-installs/1)."""
    return config_dir() / "installs.json"


def venv_dir() -> Path:
    return data_dir() / "venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def root_file() -> Path:
    """Куда лаунчер, запущенный отдельно от экосистемы, её скачал (`Скачать с GitHub`)."""
    return config_dir() / "ecosystem-root.json"


def default_download_dir() -> Path:
    return Path.home() / "p2pkanban-ecosystem"


def saved_root() -> Path | None:
    try:
        value = json.loads(root_file().read_text(encoding="utf-8")).get("root")
    except (OSError, ValueError, AttributeError):
        return None
    path = Path(value) if isinstance(value, str) and value else None
    return path if path and (path / "ecosystem.json").is_file() else None


def save_root(root: Path) -> None:
    path = root_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"root": str(root)}, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def ecosystem_root(start: Path = LAUNCHER_DIR) -> Path | None:
    """Корень экосистемы — непосредственный родитель каталога лаунчера.

    Как и правило номера патча (board/README.md), направление смотрит только на
    своего родителя и только на файлы корня, а не в соседние направления.
    Лаунчер, распакованный отдельно (например, присланный zip-ом), берёт
    каталог, куда он сам скачал экосистему.
    """
    parent = start.parent
    if (parent / "ecosystem.json").is_file():
        return parent
    return saved_root() if start == LAUNCHER_DIR else None
