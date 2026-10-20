"""Обновить checkout, из которого запущен лаунчер (ступень L5, E-ADR-004 п.8).

Git-checkout обновляется `git pull --ff-only` и только чистый: лаунчер не
сливает и не откатывает чужую работу. Распакованный архивом (get.py --archive)
каталог обновляется архивом main поверх: файлы перезаписываются, локальное
состояние направлений (например, web/.dev-bootstrap) не трогается.

Установленные направления этим не обновляются: web обновляет свой узел своей
командой update, abl пересобирается своей update из обновлённого checkout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import paths

STATUS_SCHEMA = "p2p-kanban-launcher-status/1"


def _git(root: Path, *arguments: str, timeout: float = 120) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, (done.stdout + done.stderr).strip()


def archive_marker(root: Path) -> dict | None:
    try:
        value = json.loads((root / ".launcher-archive.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def mode(root: Path | None) -> str:
    if root is None:
        return "none"
    if (root / ".git").exists():
        return "git"
    return "archive" if archive_marker(root) else "none"


def revision(root: Path | None) -> str | None:
    """Коммит монорепозитория, из которого лаунчер сейчас запущен."""
    kind = mode(root)
    if kind == "git":
        code, out = _git(root, "rev-parse", "HEAD", timeout=15)
        return out if code == 0 and len(out) == 40 else None
    if kind == "archive":
        commit = (archive_marker(root) or {}).get("commit")
        return commit if isinstance(commit, str) and len(commit) == 40 else None
    return None


def status_payload(root: Path | None, version: str) -> dict:
    """Ответ `self-status --json` по контракту launcher-entry/1: лаунчер объявляет и себя."""
    kind = mode(root)
    detail = {"git": "git-checkout", "archive": "распакован из архива main",
              "none": "запущен не из checkout экосистемы"}[kind]
    return {"schema": STATUS_SCHEMA, "component": "launcher", "installed": True, "running": True,
            "version": version, "revision": revision(root), "url": None, "values": {},
            "detail": detail, "problems": []}


def update_git(root: Path, branch: str, dry_run: bool, say: Callable[[str], None]) -> int:
    code, current = _git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=15)
    if code != 0:
        say(f"git не отвечает: {current}")
        return 1
    if current != branch:
        say(f"Checkout на ветке {current}, а не {branch}: обновите сами (git switch {branch}).")
        return 2
    code, dirty = _git(root, "status", "--porcelain", "--untracked-files=no", timeout=30)
    if dirty:
        say("В checkout есть незакоммиченные правки отслеживаемых файлов — лаунчер их не трогает:")
        for line in dirty.splitlines()[:10]:
            say(f"  {line}")
        return 2
    say(f"$ git fetch origin {branch}")
    code, out = _git(root, "fetch", "origin", branch)
    if code != 0:
        say(out)
        return code
    _, behind = _git(root, "rev-list", "--count", f"HEAD..origin/{branch}", timeout=15)
    _, ahead = _git(root, "rev-list", "--count", f"origin/{branch}..HEAD", timeout=15)
    if behind == "0":
        say("Checkout уже как main.")
        return 0
    if ahead not in ("0", ""):
        say(f"В checkout {ahead} коммит(ов), которых нет в main: fast-forward невозможен, лаунчер не сливает.")
        return 2
    _, log = _git(root, "log", "--oneline", f"HEAD..origin/{branch}", timeout=15)
    say(f"Новых коммитов в main: {behind}")
    for line in log.splitlines()[:15]:
        say(f"  {line}")
    if dry_run:
        say("Пробный прогон: checkout не изменён.")
        return 0
    say(f"$ git merge --ff-only origin/{branch}")
    code, out = _git(root, "merge", "--ff-only", f"origin/{branch}")
    say(out)
    if code == 0:
        say("Готово. Перезапустите лаунчер, чтобы взять его новую версию.")
    return code


def update_archive(root: Path, dry_run: bool, say: Callable[[str], None]) -> int:
    sys.path.insert(0, str(paths.LAUNCHER_DIR))
    import get  # noqa: WPS433 — тот же код, что ставит лаунчер на новую машину

    marker = archive_marker(root) or {}
    repository, branch = marker.get("repository") or get.REPOSITORY, marker.get("branch") or get.BRANCH
    commit = get.archive_commit(repository, branch)
    if commit and commit == marker.get("commit"):
        say(f"Каталог уже как main ({commit[:12]}).")
        return 0
    say(f"main: {(commit or 'неизвестен')[:12]}, у вас: {(marker.get('commit') or 'неизвестен')[:12]}.")
    say("Архив main распакуется поверх: файлы перезапишутся, локальное состояние направлений останется; "
        "файлы, удалённые в main, останутся у вас.")
    if dry_run:
        say("Пробный прогон: ничего не скачано.")
        return 0
    return get.archive_get(root, repository, branch, marker.get("only") or [])


def update(root: Path | None, branch: str = "main", dry_run: bool = False, say: Callable[[str], None] = print) -> int:
    kind = mode(root)
    if kind == "git":
        return update_git(root, branch, dry_run, say)
    if kind == "archive":
        return update_archive(root, dry_run, say)
    say("Лаунчер запущен не из checkout экосистемы: обновлять нечего. Новая машина — launcher/get.py.")
    return 2
