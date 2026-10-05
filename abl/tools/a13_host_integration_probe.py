#!/usr/bin/env python3
"""A13 host probe for Linux desktop capability detection and validated deep-link routing.

Uses only the already-built native binary and isolated XDG directories. It does not
install/start D-Bus services, touch systemd, use sudo, or contact the network.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "src-tauri" / "target" / "debug" / "p2pkanban-arch-native"
VALID_LINK = "p2pkanban://board/11111111-2222-4333-8444-555555555555"


def fail(message: str) -> None:
    raise SystemExit("A13 integration probe failed: " + message)


def isolated_env(base: Path) -> dict[str, str]:
    env = os.environ.copy()
    original_runtime = env.get("XDG_RUNTIME_DIR")
    wayland_display = env.get("WAYLAND_DISPLAY")
    if wayland_display and not os.path.isabs(wayland_display) and original_runtime:
        # Keep the compositor connection usable after the app runtime directory is
        # isolated. libwayland accepts an absolute WAYLAND_DISPLAY socket path.
        env["WAYLAND_DISPLAY"] = str(Path(original_runtime) / wayland_display)
    if not env.get("DBUS_SESSION_BUS_ADDRESS") and original_runtime:
        session_bus = Path(original_runtime) / "bus"
        if session_bus.exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={session_bus}"

    for key, suffix in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_STATE_HOME", "state"),
    ):
        path = base / suffix
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[key] = str(path)
    runtime = base / "runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    return env


def capability_probe(env: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        [str(BINARY), "--integration-capabilities-json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=8,
    )
    if result.returncode != 0:
        fail(f"capability probe returned {result.returncode}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        fail(f"capability probe did not emit JSON: {exc}; stdout={result.stdout!r}")
    required = {
        "sessionType", "desktop", "sessionBus", "notifications", "statusNotifier",
        "portal", "runtimeActivation", "trayLifecycle", "systemdUserService",
    }
    if set(payload) != required:
        fail(f"unexpected capability keys: {sorted(payload)}")
    if payload["sessionType"] not in {"wayland", "x11", "unknown"}:
        fail("invalid sessionType")
    for key in ("sessionBus", "notifications", "statusNotifier", "portal", "runtimeActivation"):
        if payload[key] not in {"available", "unavailable"}:
            fail(f"invalid capability value for {key}")
    if payload["trayLifecycle"] != "disabled" or payload["systemdUserService"] != "disabled":
        fail("A13 must not silently enable tray/background lifecycle")
    return payload


def start_primary(env: dict[str, str]) -> subprocess.Popen[str]:
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


def main() -> int:
    if os.geteuid() == 0:
        fail("normal-use integration evidence must be collected as a non-root user")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        fail(f"built executable missing or not executable: {BINARY}")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        fail("a real X11 or Wayland session is required for deep-link focus routing evidence")

    with tempfile.TemporaryDirectory(prefix="p2pkanban-a13-integration-") as temp:
        root = Path(temp)
        env = isolated_env(root / "normal")
        normal = capability_probe(env)
        if normal["sessionType"] == "unknown":
            fail("graphical host was not recognized as Wayland or X11")

        degraded_env = isolated_env(root / "degraded")
        degraded_env["XDG_SESSION_TYPE"] = "wayland"
        degraded_env["WAYLAND_DISPLAY"] = "a13-probe"
        degraded_env.pop("DISPLAY", None)
        degraded_env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/p2pkanban-a13-bus"
        degraded = capability_probe(degraded_env)
        if degraded["sessionType"] != "wayland":
            fail("Wayland capability fallback probe drifted")
        for key in ("sessionBus", "notifications", "statusNotifier", "portal"):
            if degraded[key] != "unavailable":
                fail(f"missing session D-Bus must degrade {key} to unavailable")

        malformed = subprocess.run(
            [str(BINARY), "p2pkanban://board/not-a-uuid"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=8,
        )
        if malformed.returncode == 0 or "invalid p2pkanban deep link" not in malformed.stderr:
            fail("malformed deep link was not rejected before runtime routing")

        primary = start_primary(env)
        try:
            time.sleep(1.5)
            if primary.poll() is not None:
                out, err = primary.communicate(timeout=1)
                fail(f"primary exited early ({primary.returncode}) stdout={out!r} stderr={err!r}")
            secondary = subprocess.run(
                [str(BINARY), VALID_LINK],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=8,
            )
            if secondary.returncode != 0:
                fail(f"deep-link secondary returned {secondary.returncode}: {secondary.stderr.strip()}")
            if "validated deep link routed to the primary instance" not in secondary.stderr:
                fail(f"secondary did not report validated routing: {secondary.stderr!r}")
            time.sleep(0.5)
        finally:
            _out, primary_err = stop(primary)
        if "accepted validated deep-link target=board" not in primary_err:
            fail(f"primary did not accept routed board intent: {primary_err!r}")

    print("A13 host integration capabilities/deep-link routing: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
