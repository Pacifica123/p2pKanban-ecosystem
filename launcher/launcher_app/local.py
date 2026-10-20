"""Локальное состояние: checkout экосистемы и реестр установок лаунчера.

Checkout читается только через git корня (какой коммит последним менял
каталог, есть ли незакоммиченные правки) — в файлы соседних направлений
лаунчер не заглядывает.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REGISTRY_SCHEMA = "p2p-kanban-launcher-installs/1"


def _git(root: Path, *arguments: str, timeout: float = 15.0) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, done.stdout


def checkout_state(root: Path | None, directories: list[str]) -> dict:
    if root is None:
        return {"available": False, "reason": "лаунчер запущен не из checkout экосистемы", "directories": {}}
    if not shutil.which("git"):
        return {"available": False, "reason": "git не найден: состояние checkout неизвестно", "directories": {}}
    code, head = _git(root, "rev-parse", "HEAD")
    if code != 0:
        return {"available": False, "reason": "каталог не является git-checkout (например, распакован из архива)", "directories": {}}
    _, branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    state = {"available": True, "reason": None, "root": str(root), "head": head.strip(),
             "branch": branch.strip(), "directories": {}}
    for directory in directories:
        present = (root / directory).is_dir()
        entry: dict = {"present": present, "commit": None, "dirty": 0}
        code, out = _git(root, "log", "-1", "--format=%H%x00%cI%x00%s", "--", directory)
        if code == 0 and out.strip():
            sha, date, subject = (out.strip().split("\x00") + ["", ""])[:3]
            entry["commit"] = {"sha": sha, "date": date, "subject": subject}
        code, out = _git(root, "status", "--porcelain", "--", directory)
        if code == 0:
            entry["dirty"] = len([line for line in out.splitlines() if line.strip()])
        state["directories"][directory] = entry
    return state


def commits_behind(root: Path | None, local_sha: str | None, remote_sha: str | None, directory: str) -> int | None:
    """Сколько коммитов каталога между локальным и remote, если remote уже скачан."""
    if not (root and local_sha and remote_sha) or local_sha == remote_sha:
        return 0 if local_sha and local_sha == remote_sha else None
    code, _ = _git(root, "cat-file", "-e", f"{remote_sha}^{{commit}}")
    if code != 0:
        return None
    code, out = _git(root, "rev-list", "--count", f"{local_sha}..{remote_sha}", "--", directory)
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def is_ancestor(root: Path | None, older: str | None, newer: str | None) -> bool | None:
    if not (root and older and newer):
        return None
    code, _ = _git(root, "cat-file", "-e", f"{newer}^{{commit}}")
    if code != 0:
        return None
    code, _ = _git(root, "merge-base", "--is-ancestor", older, newer)
    return code == 0


def read_registry(path: Path) -> dict:
    """Реестр установок лаунчера; пустой, пока лаунчер ничего не ставил (до L2)."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": REGISTRY_SCHEMA, "installs": {}}
    if not isinstance(value, dict) or not isinstance(value.get("installs"), dict):
        return {"schema": REGISTRY_SCHEMA, "installs": {}}
    return value
