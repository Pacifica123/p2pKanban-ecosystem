#!/usr/bin/env python3
"""A14 real-binary probe for the explicit bounded LAN compatibility listener.

The normal application still owns no TCP listener. This probe can start the
loopback-only test adapter only when the dedicated UTS environment flag is set.
It never changes firewall state and uses only the Python standard library.
"""
from __future__ import annotations

import http.client
import json
import os
import select
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "src-tauri" / "target" / "debug" / "p2pkanban-arch-native"


def fail(message: str) -> None:
    raise SystemExit("A14 LAN bridge probe failed: " + message)


def isolated_env(base: Path) -> dict[str, str]:
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
    runtime = base / "runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    return env


def read_descriptor(proc: subprocess.Popen[str], timeout: float = 4.0) -> dict[str, object]:
    if proc.stdout is None:
        fail("probe stdout pipe unavailable")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            fail(f"probe exited before descriptor: rc={proc.returncode} stderr={stderr!r}")
        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
        if not ready:
            continue
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            fail(f"descriptor was not JSON: {exc}: {line!r}")
        if not isinstance(payload, dict):
            fail("descriptor was not an object")
        return payload
    fail("timed out waiting for probe descriptor")


def post_envelope(endpoint: str, envelope: str) -> tuple[int, dict[str, object]]:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        fail(f"host probe escaped loopback: {endpoint!r}")
    if not (49152 <= parsed.port <= 65535):
        fail(f"host probe did not choose a random high port: {parsed.port}")
    if parsed.path != "/v1/p2pkanban/pair" or parsed.query or parsed.fragment:
        fail(f"unexpected bridge endpoint: {endpoint!r}")
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        body = envelope.encode("utf-8")
        connection.request(
            "POST",
            parsed.path,
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        raw = response.read()
    finally:
        connection.close()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"bridge response was not JSON: {exc}; raw={raw!r}")
    return response.status, payload


def main() -> int:
    if os.geteuid() == 0:
        fail("normal-use bridge evidence must be collected as a non-root user")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        fail(f"built executable missing or not executable: {BINARY}")

    # The special probe mode itself must fail closed without explicit UTS opt-in.
    denied = subprocess.run(
        [str(BINARY), "--lan-bridge-host-probe"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    if denied.returncode == 0 or "reserved for UserTestSpace verification" not in denied.stderr:
        fail("loopback host-probe mode did not fail closed without its explicit environment gate")

    with tempfile.TemporaryDirectory(prefix="p2pkanban-a14-lan-") as temp:
        env = isolated_env(Path(temp))
        env["P2PKANBAN_UTS_LAN_BRIDGE_PROBE"] = "1"
        proc = subprocess.Popen(
            [str(BINARY), "--lan-bridge-host-probe"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            descriptor = read_descriptor(proc)
            if set(descriptor) != {"protocol", "endpoint", "envelope", "expiresAtUnix"}:
                fail(f"unexpected descriptor keys: {sorted(descriptor)}")
            if descriptor["protocol"] != "p2p-kanban-lan-bridge/1":
                fail("probe protocol drifted")
            if "capability" in json.dumps(descriptor).lower() or "token" in json.dumps(descriptor).lower():
                fail("probe leaked raw one-time capability material into its descriptor/log")
            endpoint = descriptor.get("endpoint")
            envelope = descriptor.get("envelope")
            if not isinstance(endpoint, str) or not isinstance(envelope, str):
                fail("descriptor endpoint/envelope types are invalid")
            status, response = post_envelope(endpoint, envelope)
            if status != 200 or response.get("probe") != "a14":
                fail(f"authenticated one-time request failed: status={status} response={response!r}")
            try:
                return_code = proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.terminate()
                fail("bridge did not auto-close after the authenticated one-time request")
            if return_code != 0:
                stderr = proc.stderr.read() if proc.stderr else ""
                fail(f"probe process failed after accepted request: rc={return_code} stderr={stderr!r}")

            # The same endpoint must be gone after one successful request.
            parsed = urlsplit(endpoint)
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=0.5)
            try:
                try:
                    connection.request("POST", parsed.path, body=envelope, headers={"Content-Type": "application/json"})
                    connection.getresponse()
                except OSError:
                    pass
                else:
                    fail("one-time bridge endpoint remained reachable after successful consumption")
            finally:
                connection.close()
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

    print("A14 bounded LAN bridge real-binary one-time/auto-close probe: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
