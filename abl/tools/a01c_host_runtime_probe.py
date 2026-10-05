#!/usr/bin/env python3
"""A01c Linux user-session runtime evidence probe.

This is a strict host probe, not a generic devctl gate. It never installs packages,
contacts registries, invokes sudo/systemd, or weakens failure to a skip.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "src-tauri" / "target" / "debug" / "p2pkanban-arch-native"
FORBIDDEN_PROCESS_TOKENS = ("node", "postgres", "postmaster", "docker", "dockerd", "podman", "systemd")
FORBIDDEN_LINK_TOKENS = ("libpq", "libnode")


def fail(message: str) -> None:
    raise SystemExit("A01c runtime probe failed: " + message)


def capture(cmd: list[str], *, check: bool = False) -> str:
    p = subprocess.run(cmd, text=True, capture_output=True)
    if check and p.returncode != 0:
        fail(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr.strip()}")
    return (p.stdout + p.stderr).strip()


def os_release() -> dict[str, str]:
    result: dict[str, str] = {}
    path = Path("/etc/os-release")
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key] = value.strip().strip('"')
    return result


def pkg_version(module: str) -> str | None:
    if not shutil.which("pkg-config"):
        return None
    p = subprocess.run(["pkg-config", "--modversion", module], text=True, capture_output=True)
    return p.stdout.strip() if p.returncode == 0 else None


def command_version(name: str, args: list[str]) -> str | None:
    if not shutil.which(name):
        return None
    text = capture([name, *args])
    return text.splitlines()[0] if text else "present"


def parse_proc_stat(path: Path) -> tuple[int, int] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        right = text.rfind(")")
        if right < 0:
            return None
        pid = int(text[: text.find(" ")])
        rest = text[right + 2 :].split()
        ppid = int(rest[1])
        return pid, ppid
    except (OSError, ValueError, IndexError):
        return None


def descendants(root_pid: int) -> set[int]:
    parent: dict[int, int] = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        parsed = parse_proc_stat(stat)
        if parsed:
            parent[parsed[0]] = parsed[1]
    result = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, ppid in parent.items():
            if ppid in result and pid not in result:
                result.add(pid)
                changed = True
    return result


def process_record(pid: int) -> dict[str, object]:
    base = Path("/proc") / str(pid)
    try:
        comm = (base / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        comm = "<exited>"
    try:
        raw = (base / "cmdline").read_bytes()
        argv0 = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    except OSError:
        argv0 = ""
    try:
        uid = base.stat().st_uid
    except OSError:
        uid = None
    return {"pid": pid, "uid": uid, "comm": comm, "argv0": argv0}


def socket_inodes_for(pids: set[int]) -> set[str]:
    inodes: set[str] = set()
    for pid in pids:
        fd_dir = Path("/proc") / str(pid) / "fd"
        try:
            entries = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in entries:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            m = re.fullmatch(r"socket:\[(\d+)\]", target)
            if m:
                inodes.add(m.group(1))
    return inodes


def listening_tcp(inodes: set[str]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for proc_file in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = proc_file.read_text(encoding="ascii", errors="replace").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":  # TCP_LISTEN
                continue
            inode = fields[9]
            if inode in inodes:
                found.append({"family": proc_file.name, "local": fields[1], "inode": inode})
    return found


def dependency_report(binary: Path) -> str:
    if not shutil.which("ldd"):
        fail("ldd is required for Linux dynamic dependency evidence")
    text = capture(["ldd", str(binary)], check=True)
    lowered = text.lower()
    bad = [token for token in FORBIDDEN_LINK_TOKENS if token in lowered]
    if bad:
        fail("forbidden runtime-linked dependency detected: " + ", ".join(bad))
    return text


def environment_report() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "os_release": os_release(),
        "euid": os.geteuid(),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
        "display": bool(os.environ.get("DISPLAY")),
        "wayland_display": bool(os.environ.get("WAYLAND_DISPLAY")),
        "commands": {
            "rustc": command_version("rustc", ["--version"]),
            "cargo": command_version("cargo", ["--version"]),
            "node": command_version("node", ["--version"]),
            "npm": command_version("npm", ["--version"]),
            "pkg-config": shutil.which("pkg-config"),
        },
        "libraries": {
            name: pkg_version(name)
            for name in ("webkit2gtk-4.1", "gtk+-3.0", "glib-2.0")
        },
        "systemctl_command_present": bool(shutil.which("systemctl")),
        "dbus_session_bus_present": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
    }


def doctor() -> int:
    print(json.dumps(environment_report(), indent=2, sort_keys=True))
    return 0


def launch_probe(seconds: float, report_path: Path | None) -> int:
    if os.geteuid() == 0:
        fail("normal-use launch evidence must be collected as a non-root user")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        fail(f"built executable missing or not executable: {BINARY}")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        fail("a real X11 or Wayland user session is required; headless success is not launch evidence")

    deps = dependency_report(BINARY)
    canary = "A01C_SECRET_CANARY_7f865bcb2d8e4d06"
    with tempfile.TemporaryDirectory(prefix="p2pkanban-a01c-") as temp:
        base = Path(temp)
        runtime = base / "runtime"
        runtime.mkdir(mode=0o700)
        env = os.environ.copy()
        env.update({
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_DATA_HOME": str(base / "data"),
            "XDG_CACHE_HOME": str(base / "cache"),
            "XDG_STATE_HOME": str(base / "state"),
            "XDG_RUNTIME_DIR": str(runtime),
            "P2PKANBAN_TEST_SECRET_CANARY": canary,
        })
        for name in ("config", "data", "cache", "state"):
            (base / name).mkdir()

        proc = subprocess.Popen(
            [str(BINARY)], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        try:
            time.sleep(seconds)
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=1)
                fail(f"application exited before evidence window (code {proc.returncode})\nstdout={out}\nstderr={err}")

            pids = descendants(proc.pid)
            processes = [process_record(pid) for pid in sorted(pids)]
            bad_processes = []
            for record in processes:
                haystack = f"{record['comm']} {record['argv0']}".lower()
                if any(re.search(rf"(^|[/ _.-]){re.escape(token)}($|[/ _.-])", haystack) for token in FORBIDDEN_PROCESS_TOKENS):
                    bad_processes.append(record)
            if bad_processes:
                fail("forbidden runtime child/process dependency observed: " + json.dumps(bad_processes))

            listeners = listening_tcp(socket_inodes_for(pids))
            if listeners:
                fail("normal shell opened TCP listening socket(s): " + json.dumps(listeners))

            report = {
                "result": "pass",
                "probe_seconds": seconds,
                "environment": environment_report(),
                "processes": processes,
                "tcp_listeners": listeners,
                "dynamic_dependencies": deps.splitlines(),
                "xdg_isolated": True,
                "root_required": False,
                "forbidden_process_dependency_observed": False,
                "secret_canary_logged": False,
                "navigation_runtime_probe": "not-covered-by-this-command",
            }
        finally:
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
            out, err = proc.communicate(timeout=2)

        combined = (out or "") + "\n" + (err or "")
        if canary in combined:
            fail("secret canary appeared in application stdout/stderr")
        out_bytes = (out or "").encode("utf-8", errors="replace")
        err_bytes = (err or "").encode("utf-8", errors="replace")
        report["stdout_bytes"] = len(out_bytes)
        report["stderr_bytes"] = len(err_bytes)
        report["stdout_sha256"] = hashlib.sha256(out_bytes).hexdigest()
        report["stderr_sha256"] = hashlib.sha256(err_bytes).hexdigest()
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    launch = sub.add_parser("launch-probe")
    launch.add_argument("--seconds", type=float, default=4.0)
    launch.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "doctor":
        return doctor()
    return launch_probe(args.seconds, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
