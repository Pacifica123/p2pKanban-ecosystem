#!/usr/bin/env python3
"""A18 shared measurement plumbing: process-tree sampling, isolated XDG, budgets.

Only /proc and the already-built binary are used. Nothing here installs
packages, uses sudo/systemctl, suspends the host or touches the user's real
XDG profile. Every number is labelled with how it was measured, because several
of them are proxies (see docs/A18_PERFORMANCE_POWER_ROLLING.md).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = ROOT / "packaging" / "budgets" / "a18-budgets.json"
BINARY_NAME = "p2pkanban-arch-native"
CLK_TCK = os.sysconf("SC_CLK_TCK")
WEBKIT_COMM_PREFIX = "WebKit"  # comm is truncated to 15 chars: WebKitWebProces, WebKitNetworkPr


def binary_path(profile: str) -> Path:
    """`P2PKANBAN_A18_BINARY` exists only for check_a18's stub self-test."""
    override = os.environ.get("P2PKANBAN_A18_BINARY")
    if override:
        return Path(override)
    if profile not in {"debug", "release"}:
        raise SystemExit(f"unsupported build profile: {profile}")
    return ROOT / "src-tauri" / "target" / profile / BINARY_NAME


def isolated_env(base: Path, *, keep_display: bool = True) -> dict[str, str]:
    env = os.environ.copy()
    home = base / "home"
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    env["HOME"] = str(home)
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
    if not keep_display:
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
    return env


def profile_db(base: Path) -> Path:
    return base / "data" / "p2pkanban" / "profiles" / "default" / "profile.db"


def require_session(binary: Path) -> None:
    if os.geteuid() == 0:
        raise SystemExit("A18 evidence must be collected as a non-root user")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SystemExit(f"built executable missing or not executable: {binary}")


def require_display() -> None:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise SystemExit("a real X11 or Wayland user session is required; headless success is not runtime evidence")


# ---------------------------------------------------------------- /proc reading

def _stat_fields(pid: int) -> list[str] | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    right = text.rfind(")")
    if right < 0:
        return None
    return text[right + 2:].split()


def parent_map() -> dict[int, int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        fields = _stat_fields(int(entry.name))
        if fields:
            try:
                parents[int(entry.name)] = int(fields[1])
            except (ValueError, IndexError):
                pass
    return parents


def tree(root_pid: int) -> set[int]:
    parents = parent_map()
    if root_pid not in parents:
        return set()
    result = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, ppid in parents.items():
            if ppid in result and pid not in result:
                result.add(pid)
                changed = True
    return result


def comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "<exited>"


def cpu_ticks(pid: int) -> int:
    fields = _stat_fields(pid)
    if not fields:
        return 0
    try:
        return int(fields[11]) + int(fields[12])  # utime + stime, all threads
    except (ValueError, IndexError):
        return 0


def context_switches(pid: int) -> dict[str, int]:
    """Per-thread counters: /proc/<pid>/status alone counts only the main thread,
    and a thread that exits mid-window must not turn the delta negative."""
    result: dict[str, int] = {}
    try:
        tasks = list(Path(f"/proc/{pid}/task").iterdir())
    except OSError:
        return result
    for task in tasks:
        total = 0
        try:
            for line in (task / "status").read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith(("voluntary_ctxt_switches:", "nonvoluntary_ctxt_switches:")):
                    total += int(line.split()[1])
        except (OSError, ValueError, IndexError):
            continue
        result[f"{pid}/{task.name}"] = total
    return result


def switches_delta(before: dict[str, int], after: dict[str, int]) -> int:
    """Threads alive at both samples, plus everything a new thread did."""
    return sum(count - before.get(tid, 0) for tid, count in after.items() if count >= before.get(tid, 0))


def memory_kib(pid: int) -> tuple[int | None, int | None]:
    """(Pss, Rss) in KiB from smaps_rollup; None when the kernel hides it."""
    try:
        text = Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    values: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^(Pss|Rss):\s+(\d+) kB", line)
        if match:
            values[match.group(1)] = int(match.group(2))
    return values.get("Pss"), values.get("Rss")


def inet_sockets(pids: set[int]) -> dict[str, int]:
    """Count TCP/UDP sockets (any state) owned by the tree, split by listen/other."""
    inodes: set[str] = set()
    for pid in pids:
        try:
            fds = list(Path(f"/proc/{pid}/fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", target)
            if match:
                inodes.add(match.group(1))
    counts = {"tcpListen": 0, "tcpOther": 0, "udp": 0}
    for name in ("tcp", "tcp6", "udp", "udp6"):
        try:
            lines = Path(f"/proc/net/{name}").read_text(encoding="ascii", errors="replace").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[9] not in inodes:
                continue
            if name.startswith("udp"):
                counts["udp"] += 1
            elif fields[3] == "0A":
                counts["tcpListen"] += 1
            else:
                counts["tcpOther"] += 1
    return counts


def dir_kib(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total // 1024


# ---------------------------------------------------------------- running the app

class App:
    """One GUI process tree with stdout/stderr in files (a full pipe would stall it)."""

    def __init__(self, binary: Path, env: dict[str, str], log_dir: Path, name: str,
                 args: list[str] | None = None, wrapper: list[str] | None = None) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self.stdout_path = log_dir / f"{name}.stdout.log"
        self.stderr_path = log_dir / f"{name}.stderr.log"
        self._out = self.stdout_path.open("wb")
        self._err = self.stderr_path.open("wb")
        self.started = time.monotonic()
        self.proc = subprocess.Popen(
            [*(wrapper or []), str(binary), *(args or [])], cwd=ROOT, env=env,
            stdout=self._out, stderr=self._err, start_new_session=True,
        )
        # pid -> kernel start time, so a recycled pid is never mistaken for ours
        self.seen: dict[int, str] = {}
        self.web_process_seen = False

    @property
    def pid(self) -> int:
        return self.proc.pid

    def alive(self) -> bool:
        return self.proc.poll() is None

    def pids(self) -> set[int]:
        current = tree(self.proc.pid)
        for pid in current:
            self.seen.setdefault(pid, start_time(pid))
        if any(comm(pid).startswith(WEBKIT_COMM_PREFIX) for pid in current):
            self.web_process_seen = True
        return current

    def ticks(self) -> int:
        return sum(cpu_ticks(pid) for pid in self.pids())

    def wait_settled(self, timeout: float, *, quiet_percent: float = 5.0,
                     window: float = 0.5, webkit_grace: float = 10.0) -> float:
        """Milliseconds from spawn until the tree's CPU stays under quiet_percent
        of one core for a whole window, after the WebKit web process exists
        (or webkit_grace seconds passed without one). Raises on exit/timeout."""
        deadline = self.started + timeout
        min_start = self.started + 1.0
        while time.monotonic() < deadline:
            if not self.alive():
                raise RuntimeError(f"application exited during startup (code {self.proc.returncode})")
            before = self.ticks()
            t0 = time.monotonic()
            time.sleep(window)
            used = (self.ticks() - before) / CLK_TCK
            elapsed = time.monotonic() - t0
            ready = self.web_process_seen or time.monotonic() - self.started > webkit_grace
            if ready and t0 >= min_start and used / elapsed * 100 < quiet_percent:
                return round((time.monotonic() - self.started) * 1000)
        raise RuntimeError(f"process tree did not settle within {timeout}s")

    def idle_window(self, seconds: float) -> dict[str, object]:
        pids = self.pids()
        ticks0 = sum(cpu_ticks(pid) for pid in pids)
        switches0: dict[str, int] = {}
        for pid in pids:
            switches0.update(context_switches(pid))
        t0 = time.monotonic()
        time.sleep(seconds)
        if not self.alive():
            raise RuntimeError("application exited during the idle window")
        pids = self.pids()
        elapsed = time.monotonic() - t0
        ticks1 = sum(cpu_ticks(pid) for pid in pids)
        switches1: dict[str, int] = {}
        for pid in pids:
            switches1.update(context_switches(pid))
        pss = rss = 0
        hidden = []
        for pid in pids:
            p, r = memory_kib(pid)
            if p is None:
                hidden.append(pid)
            else:
                pss += p
                rss += r or 0
        sockets = inet_sockets(pids)
        return {
            "seconds": round(elapsed, 2),
            "idleCpuPercent": round((ticks1 - ticks0) / CLK_TCK / elapsed * 100, 3),
            "idleWakeupsPerSecond": round(switches_delta(switches0, switches1) / elapsed, 2),
            "idlePssMiB": round(pss / 1024, 1),
            "idleRssMiB": round(rss / 1024, 1),
            "memoryHiddenPids": hidden,
            "idleInetSockets": sockets["tcpListen"] + sockets["tcpOther"] + sockets["udp"],
            "sockets": sockets,
            "processes": sorted({comm(pid) for pid in pids}),
            "processCount": len(pids),
        }

    def signal_tree(self, sig: int) -> None:
        for pid in sorted(self.pids(), reverse=True):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    def stop(self, timeout: float = 5.0) -> int:
        """SIGTERM the main process only (what a window close/logout delivers), then
        count every process ever seen in the tree that is still alive."""
        self.pids()
        pids = dict(self.seen)
        if self.alive():
            try:
                os.kill(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + timeout
        survivors = pids
        while time.monotonic() < deadline:
            self.proc.poll()
            survivors = {pid for pid, started in pids.items() if _same_live_process(pid, started)}
            if not survivors:
                break
            time.sleep(0.1)
        for pid in survivors:  # never leave anything behind on the host
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self._out.close()
        self._err.close()
        return len(survivors)

    def kill(self) -> None:
        self.signal_tree(signal.SIGKILL)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self._out.close()
        self._err.close()


def start_time(pid: int) -> str:
    fields = _stat_fields(pid)
    return fields[19] if fields and len(fields) > 19 else ""


def _same_live_process(pid: int, started: str) -> bool:
    fields = _stat_fields(pid)
    return bool(fields) and len(fields) > 19 and fields[19] == started and fields[0] not in {"Z", "X"}


def run_cli(binary: Path, args: list[str], env: dict[str, str], timeout: float = 120) -> tuple[subprocess.CompletedProcess[str], float]:
    start = time.monotonic()
    result = subprocess.run([str(binary), *args], cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=timeout)
    return result, round((time.monotonic() - start) * 1000, 1)


# ---------------------------------------------------------------- budgets

def load_budgets(path: Path = BUDGETS) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_budgets(data)
    return data


def validate_budgets(data: dict) -> None:
    if data.get("format") != "p2pkanban-a18-budgets" or data.get("formatVersion") != 1:
        raise ValueError("unsupported budgets format")
    if data.get("status") not in {"proposed", "accepted"}:
        raise ValueError("budgets status must be proposed or accepted")
    allowance = data.get("debugAllowance", {})
    ids: set[str] = set()
    for budget in data.get("budgets", []):
        for key in ("id", "scenario", "metric", "max", "kind", "unit"):
            if key not in budget:
                raise ValueError(f"budget missing {key}: {budget}")
        if budget["id"] in ids:
            raise ValueError(f"duplicate budget id {budget['id']}")
        ids.add(budget["id"])
        if budget["kind"] not in {"time", "cpu", "memory", "disk", "invariant"}:
            raise ValueError(f"unknown budget kind {budget['kind']}")
        if budget["kind"] != "invariant" and budget["kind"] not in allowance:
            raise ValueError(f"no debug allowance for kind {budget['kind']}")
        if not isinstance(budget["max"], (int, float)) or budget["max"] < 0:
            raise ValueError(f"budget max must be a non-negative number: {budget['id']}")
    for deviation in data.get("acceptedDeviations", []):
        if deviation.get("budgetId") not in ids or not str(deviation.get("adr", "")).startswith("ADR-"):
            raise ValueError(f"accepted deviation must name a known budget and an ADR: {deviation}")


def evaluate(data: dict, measured: dict[str, dict[str, object]], profile: str) -> list[dict[str, object]]:
    """measured: scenario -> metric -> value. Invariants never get a debug allowance."""
    deviations = {d["budgetId"]: d for d in data.get("acceptedDeviations", [])}
    rows = []
    for budget in data["budgets"]:
        value = measured.get(budget["scenario"], {}).get(budget["metric"])
        limit = float(budget["max"])
        if profile == "debug" and budget["kind"] != "invariant":
            limit *= float(data["debugAllowance"][budget["kind"]])
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            verdict = "unmeasured"
        elif value <= limit:
            verdict = "within"
        elif budget["id"] in deviations:
            verdict = "accepted-deviation"
        else:
            verdict = "over"
        rows.append({
            "id": budget["id"], "scenario": budget["scenario"], "metric": budget["metric"],
            "kind": budget["kind"], "unit": budget["unit"], "value": value,
            "limit": round(limit, 3), "verdict": verdict,
            "adr": deviations.get(budget["id"], {}).get("adr"),
        })
    return rows


def write_report(path: Path | None, report: dict) -> None:
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
