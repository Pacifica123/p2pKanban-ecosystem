#!/usr/bin/env python3
"""Build the exact backend and web images used by zero-config bootstrap."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "deploy/bootstrap/compose.yaml"


def run(command: list[str], *, env: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("Docker CLI не найден.")

    env = os.environ.copy()
    env.update(
        {
            "P2PKANBAN_WEB_PORT": "18088",
            "P2PKANBAN_BIND_ADDRESS": "127.0.0.1",
            "P2PKANBAN_IMAGE_TAG": "devctl-v1-build-check",
            "P2PKANBAN_SOURCE_REVISION": "0" * 40,
        }
    )
    run([docker, "compose", "version"], env=env)
    run([docker, "info", "--format", "{{.ServerVersion}}"], env=env)
    run(
        [
            docker,
            "compose",
            "--progress",
            "plain",
            "--project-name",
            "p2pkanban-devctl-buildcheck",
            "--file",
            str(COMPOSE_FILE),
            "build",
            "backend",
            "web",
        ],
        env=env,
    )
    print("OK: production backend and web images built successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
