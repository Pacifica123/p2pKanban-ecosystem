#!/usr/bin/env python3
"""Repository-view helpers for deterministic gates.

The same deterministic checks run in two legitimate environments:

1. a normal devctl/Git workspace, where ``git ls-files`` is authoritative;
2. UserTestSpace snapshots, which intentionally contain no ``.git`` metadata.

In the second mode we build a deterministic snapshot inventory and exclude only
known generated/cache trees. Security-sensitive files are *not* ignored by the
fallback, even when a developer might normally add them to ``.gitignore``.
This keeps hygiene checks useful without requiring UTS to be a Git checkout.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

GENERATED_PREFIXES = (
    "node_modules/",
    "dist/",
    "target/",
    "src-tauri/target/",
    "src-tauri/gen/",
    ".uts-reports/",
    "coverage/",
    "build/",
)

GENERATED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
}

GENERATED_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tsbuildinfo",
}


def _git_tracked_relative_paths(root: Path) -> list[str] | None:
    """Return tracked paths only when *root itself* is a Git worktree.

    UTS snapshots may be nested under unrelated directories; never inherit an
    ancestor repository accidentally.
    """
    env = os.environ.copy()
    env.setdefault("GIT_DISCOVERY_ACROSS_FILESYSTEM", "0")
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return None
    if probe.returncode != 0:
        return None
    try:
        top = Path(probe.stdout.decode("utf-8", errors="strict").strip()).resolve()
    except (UnicodeDecodeError, OSError):
        return None
    if top != root.resolve():
        return None

    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed inside repository root: {message or proc.returncode}")
    return [item.decode("utf-8", errors="strict") for item in proc.stdout.split(b"\0") if item]


def _is_generated_snapshot_path(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in GENERATED_PREFIXES):
        return True
    parts = Path(rel).parts
    if any(part in GENERATED_DIR_NAMES for part in parts):
        return True
    return any(rel.endswith(suffix) for suffix in GENERATED_FILE_SUFFIXES)


def _snapshot_relative_paths(root: Path) -> list[str]:
    """Return the repository-owned view for a devctl UTS snapshot.

    Only known build/cache output is removed from the view. Files such as
    ``.env``, private keys, SQLite files, or other unexpected payload remain in
    the inventory so A00/A01 can reject them instead of silently hiding them.

    ``os.walk(topdown=True)`` is used deliberately so large Cargo/npm build
    trees are pruned before traversal; a post-build UTS check must stay O(source)
    rather than O(target/node_modules).
    """
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(dirpath)

        kept_dirs: list[str] = []
        for name in dirnames:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if rel == ".git" or rel.startswith(".git/") or _is_generated_snapshot_path(rel):
                continue
            if path.is_symlink():
                result.append(rel)
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in filenames:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if _is_generated_snapshot_path(rel):
                continue
            result.append(rel)

    return sorted(result)


def repository_view_mode(root: Path) -> str:
    return "git" if _git_tracked_relative_paths(root) is not None else "snapshot"


def tracked_relative_paths(root: Path) -> list[str]:
    """Compatibility name: return repository-owned paths in Git or UTS mode."""
    tracked = _git_tracked_relative_paths(root)
    if tracked is not None:
        return tracked
    return _snapshot_relative_paths(root)


def tracked_files(root: Path, *prefixes: str) -> list[Path]:
    normalized = tuple(prefix.rstrip("/") + "/" for prefix in prefixes)
    result: list[Path] = []
    for rel in tracked_relative_paths(root):
        if normalized and not any(rel.startswith(prefix) for prefix in normalized):
            continue
        path = root / rel
        if path.is_file():
            result.append(path)
    return result


def generated_tracked_paths(root: Path) -> list[str]:
    """Generated paths committed to Git; empty by construction in UTS mode.

    In snapshot mode generated paths are excluded from the repository-owned
    view because devctl archives intentionally omit them. Their mere presence
    after a build is therefore not a repository hygiene violation.
    """
    git_paths = _git_tracked_relative_paths(root)
    if git_paths is None:
        return []
    bad: list[str] = []
    for rel in git_paths:
        if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in GENERATED_PREFIXES):
            bad.append(rel)
        elif any(part in GENERATED_DIR_NAMES for part in Path(rel).parts):
            bad.append(rel)
        elif any(rel.endswith(suffix) for suffix in GENERATED_FILE_SUFFIXES):
            bad.append(rel)
    return bad
