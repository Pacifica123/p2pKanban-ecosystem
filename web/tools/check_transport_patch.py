#!/usr/bin/env python3
"""Run transport-patch checks without leaving generated trees in the project."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EDGE = ROOT / "edge-coordinator"


def require_command(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required command is missing: {name}")
    return resolved


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[check] cwd={cwd.relative_to(ROOT) if cwd != ROOT else '.'}")
    print("[check] " + " ".join(command))
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {command[0]}")


def check_rust() -> None:
    cargo = require_command("cargo")
    with tempfile.TemporaryDirectory(prefix="p2p-kanban-cargo-target-") as target:
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = target
        run(
            [
                cargo,
                "test",
                "--manifest-path",
                str(BACKEND / "Cargo.toml"),
                "--workspace",
                "--all-features",
                "--all-targets",
            ],
            cwd=ROOT,
            env=env,
        )


def check_edge() -> None:
    npm = require_command("npm")
    node_modules = EDGE / "node_modules"
    try:
        run([npm, "ci", "--ignore-scripts"], cwd=EDGE)
        run([npm, "run", "typecheck"], cwd=EDGE)
        run([npm, "test"], cwd=EDGE)
    finally:
        if node_modules.exists():
            shutil.rmtree(node_modules)


def main() -> int:
    try:
        check_rust()
        check_edge()
    except (OSError, RuntimeError) as error:
        print(f"[check] FAILED: {error}", file=sys.stderr)
        return 1
    print("[check] transport patch checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
