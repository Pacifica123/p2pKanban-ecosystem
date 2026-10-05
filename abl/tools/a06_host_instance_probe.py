#!/usr/bin/env python3
"""A06 host probe for single-writer instance control and XDG runtime degradation.

Runs only the already-built native binary. It does not install packages, use sudo,
contact the network, or mutate the user's real XDG directories.
"""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "src-tauri" / "target" / "debug" / "p2pkanban-arch-native"


def fail(message: str) -> None:
    raise SystemExit("A06 instance probe failed: " + message)


def isolated_env(base: Path, *, runtime: bool) -> dict[str, str]:
    env = os.environ.copy()
    for key, suffix in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_STATE_HOME", "state"),
    ):
        path = base / suffix
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[key] = str(path)
    if runtime:
        path = base / "runtime"
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        env["XDG_RUNTIME_DIR"] = str(path)
    else:
        env.pop("XDG_RUNTIME_DIR", None)
    return env


def start(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(BINARY)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def stop(proc: subprocess.Popen[str]) -> tuple[str, str]:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return proc.communicate(timeout=2)


def assert_primary_stays_running(proc: subprocess.Popen[str], label: str) -> None:
    time.sleep(1.5)
    if proc.poll() is not None:
        out, err = proc.communicate(timeout=1)
        fail(f"{label} primary exited early ({proc.returncode})\nstdout={out}\nstderr={err}")


def run_secondary(env: dict[str, str], expected: str) -> None:
    secondary = subprocess.run(
        [str(BINARY)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=8
    )
    if secondary.returncode != 0:
        fail(f"secondary returned {secondary.returncode}: {secondary.stderr.strip()}")
    combined = (secondary.stdout or "") + "\n" + (secondary.stderr or "")
    if expected not in combined:
        fail(f"secondary did not report expected instance outcome: {expected!r}; got {combined!r}")


def main() -> int:
    if os.geteuid() == 0:
        fail("normal-use instance evidence must be collected as a non-root user")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        fail(f"built executable missing or not executable: {BINARY}")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        fail("a real X11 or Wayland session is required")

    with tempfile.TemporaryDirectory(prefix="p2pkanban-a06-instance-") as temp:
        root = Path(temp)

        routed_env = isolated_env(root / "routed", runtime=True)
        primary = start(routed_env)
        try:
            assert_primary_stays_running(primary, "routed")
            run_secondary(routed_env, "activation routed to the primary instance")
            assert_primary_stays_running(primary, "routed after secondary")
        finally:
            stop(primary)

        # Kernel-owned profile lock must release when the primary process exits.
        restarted = start(routed_env)
        try:
            assert_primary_stays_running(restarted, "restart")
        finally:
            stop(restarted)

        no_runtime_env = isolated_env(root / "no-runtime", runtime=False)
        primary = start(no_runtime_env)
        try:
            assert_primary_stays_running(primary, "no-runtime")
            run_secondary(
                no_runtime_env,
                "writer ownership is protected but XDG runtime activation routing is unavailable",
            )
            assert_primary_stays_running(primary, "no-runtime after secondary")
        finally:
            stop(primary)

    print("A06 host instance control: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
