#!/usr/bin/env python3
"""A18 suspend/network/lifecycle chaos against the real GUI binary (EX-ARCH-008 subset).

    a18_host_chaos_probe.py [--profile debug|release] [--report R] [--freeze-seconds N]

Scenarios, each in its own isolated XDG directories:

  freeze-thaw     SIGSTOP the whole process tree, then SIGCONT: what the app sees
                  of a suspend. Must stay alive, return to idle without a CPU
                  catch-up storm, exit cleanly, and leave a healthy profile.
  hard-kill       SIGKILL the tree mid-session (power loss / OOM). The profile
                  must pass doctor without safe mode, and the app must start again.
  instance-storm  8 second instances at once against a running primary: all must
                  exit, the primary must not open another web view.
  bus-gone        session D-Bus address points nowhere: degraded start, no crash.
  offline-netns   start inside a fresh network namespace (no interfaces but lo)
                  via unprivileged `unshare`; recorded as unavailable, not as a
                  pass, when the kernel or util-linux does not allow it.

Not covered here and listed in the report: real systemd suspend/resume and
wall-clock jumps (need privileges or a human), relay reconnect (relay
orchestration does not exist yet, see A10). No sudo, no host suspend, no
firewall or network configuration is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from a18_common import (
    App, binary_path, comm, isolated_env, load_budgets, profile_db, require_display,
    require_session, run_cli, write_report,
)
from a18_host_budget_probe import seed_fixture

STORM = 8
THAW_CPU_CAP_PERCENT = 10.0  # average over the 10 s after SIGCONT, % of one core


class ScenarioFailed(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioFailed(message)


def doctor_healthy(binary: Path, env: dict[str, str]) -> dict:
    result, ms = run_cli(binary, ["doctor", "--json"], env)
    check(result.returncode == 0, f"doctor returned {result.returncode}: {result.stderr.strip()}")
    report = json.loads(result.stdout)
    check(report.get("safeModeRequired") is False, f"profile needs safe mode: {report.get('checks')}")
    return {"safeModeRequired": False, "schemaVersion": report.get("schemaVersion"), "doctorMs": ms}


def card_count(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM cards").fetchone()[0]
    finally:
        conn.close()


def started(binary: Path, env: dict[str, str], log_dir: Path, name: str, wrapper: list[str] | None = None) -> tuple[App, int]:
    app = App(binary, env, log_dir, name, wrapper=wrapper)
    try:
        return app, app.wait_settled(timeout=60)
    except RuntimeError as exc:
        app.kill()
        raise ScenarioFailed(f"{exc}; see {app.stderr_path}") from exc


def freeze_thaw(binary: Path, budgets: dict, base: Path, log_dir: Path, freeze: float) -> dict:
    env = isolated_env(base)
    db = profile_db(base)
    seed_fixture(db, budgets["fixture"])
    app, settle = started(binary, env, log_dir, "chaos-freeze-thaw")
    try:
        frozen = app.pids()
        app.signal_tree(signal.SIGSTOP)
        time.sleep(freeze)
        app.signal_tree(signal.SIGCONT)
        check(app.alive(), "main process died while frozen")
        after = app.idle_window(10)
        check(after["idleCpuPercent"] <= THAW_CPU_CAP_PERCENT,
              f"CPU catch-up after thaw {after['idleCpuPercent']}% > {THAW_CPU_CAP_PERCENT}%")
        check(after["idleInetSockets"] == 0, f"inet sockets after thaw: {after['sockets']}")
    except BaseException:
        app.kill()
        raise
    leftover = app.stop()
    check(leftover == 0, f"{leftover} process(es) survived exit after thaw")
    doctor = doctor_healthy(binary, env)
    cards = card_count(db)
    check(cards == budgets["fixture"]["cards"], f"card count changed: {cards}")
    return {"settleMs": settle, "frozenProcesses": len(frozen), "frozenSeconds": freeze,
            "thawCpuPercent": after["idleCpuPercent"], "thawWakeupsPerSecond": after["idleWakeupsPerSecond"],
            "processesAfterExit": leftover, "doctor": doctor, "cards": cards}


def hard_kill(binary: Path, budgets: dict, base: Path, log_dir: Path) -> dict:
    env = isolated_env(base)
    db = profile_db(base)
    seed_fixture(db, budgets["fixture"])
    app, settle = started(binary, env, log_dir, "chaos-hard-kill")
    app.kill()
    doctor = doctor_healthy(binary, env)
    cards = card_count(db)
    check(cards == budgets["fixture"]["cards"], f"card count changed after SIGKILL: {cards}")
    again, settle_again = started(binary, env, log_dir, "chaos-hard-kill-restart")
    leftover = again.stop()
    check(leftover == 0, f"{leftover} process(es) survived exit after restart")
    return {"settleMs": settle, "doctorAfterKill": doctor, "cards": cards,
            "restartSettleMs": settle_again, "processesAfterExit": leftover}


def instance_storm(binary: Path, base: Path, log_dir: Path) -> dict:
    env = isolated_env(base)
    primary, settle = started(binary, env, log_dir, "chaos-storm-primary")
    try:
        web_before = sorted(pid for pid in primary.pids() if comm(pid).startswith("WebKitWebProces"))
        storm = [subprocess.Popen([str(binary)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True) for _ in range(STORM)]
        codes = []
        for proc in storm:
            try:
                codes.append(proc.wait(timeout=20))
            except subprocess.TimeoutExpired:
                for other in storm:
                    if other.poll() is None:
                        os.killpg(other.pid, signal.SIGKILL)
                raise ScenarioFailed("a second instance kept running instead of routing to the primary")
        check(all(code == 0 for code in codes), f"second-instance exit codes: {codes}")
        time.sleep(2)
        check(primary.alive(), "primary died during the second-instance storm")
        web_after = sorted(pid for pid in primary.pids() if comm(pid).startswith("WebKitWebProces"))
        check(len(web_after) <= max(1, len(web_before)), f"primary opened extra web views: {web_before} -> {web_after}")
    except BaseException:
        primary.kill()
        raise
    leftover = primary.stop()
    check(leftover == 0, f"{leftover} process(es) survived exit")
    return {"settleMs": settle, "secondInstances": STORM, "exitCodes": codes,
            "webProcessesBefore": len(web_before), "webProcessesAfter": len(web_after), "processesAfterExit": leftover}


def bus_gone(binary: Path, base: Path, log_dir: Path) -> dict:
    env = isolated_env(base)
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/p2pkanban-a18-bus"
    app, settle = started(binary, env, log_dir, "chaos-bus-gone")
    try:
        idle = app.idle_window(5)
    except RuntimeError as exc:
        app.kill()
        raise ScenarioFailed(str(exc)) from exc
    leftover = app.stop()
    check(leftover == 0, f"{leftover} process(es) survived exit")
    return {"settleMs": settle, "idleCpuPercent": idle["idleCpuPercent"], "processesAfterExit": leftover}


def netns_wrapper() -> tuple[list[str] | None, str]:
    wrapper = ["unshare", "--user", "--map-current-user", "--net", "--"]
    try:
        probe = subprocess.run([*wrapper, "true"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"unshare not usable: {exc}"
    if probe.returncode != 0:
        return None, "unprivileged network namespace refused: " + (probe.stderr or probe.stdout).strip()
    return wrapper, ""


def offline_netns(binary: Path, base: Path, log_dir: Path) -> dict:
    wrapper, reason = netns_wrapper()
    if wrapper is None:
        return {"status": "unavailable", "reason": reason}
    env = isolated_env(base)
    app, settle = started(binary, env, log_dir, "chaos-offline-netns", wrapper=wrapper)
    try:
        idle = app.idle_window(5)
        check(idle["idleInetSockets"] == 0, f"inet sockets while offline: {idle['sockets']}")
    except RuntimeError as exc:
        app.kill()
        raise ScenarioFailed(str(exc)) from exc
    except BaseException:
        app.kill()
        raise
    leftover = app.stop()
    check(leftover == 0, f"{leftover} process(es) survived exit")
    return {"status": "pass", "settleMs": settle, "idleCpuPercent": idle["idleCpuPercent"], "processesAfterExit": leftover}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile", choices=["debug", "release"], default="debug")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--freeze-seconds", type=float, default=20.0)
    args = parser.parse_args()

    budgets = load_budgets()
    binary = binary_path(args.profile)
    require_session(binary)
    require_display()
    log_dir = (args.report.parent if args.report else Path(tempfile.gettempdir())) / "a18-app-logs"

    results: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="p2pkanban-a18-chaos-") as temp:
        work = Path(temp)
        scenarios = [
            ("freeze-thaw", lambda: freeze_thaw(binary, budgets, work / "freeze", log_dir, args.freeze_seconds)),
            ("hard-kill", lambda: hard_kill(binary, budgets, work / "kill", log_dir)),
            ("instance-storm", lambda: instance_storm(binary, work / "storm", log_dir)),
            ("bus-gone", lambda: bus_gone(binary, work / "bus", log_dir)),
            ("offline-netns", lambda: offline_netns(binary, work / "netns", log_dir)),
        ]
        for name, run in scenarios:
            try:
                outcome = run()
                outcome.setdefault("status", "pass")
            except ScenarioFailed as exc:
                outcome = {"status": "fail", "reason": str(exc)}
            results[name] = outcome
            print(f"[{outcome['status'].upper()}] {name}" + (f": {outcome['reason']}" if "reason" in outcome else ""))

    failed = [name for name, outcome in results.items() if outcome["status"] == "fail"]
    report = {
        "format": "p2pkanban-a18-chaos-probe",
        "buildProfile": args.profile,
        "scenarios": results,
        "notEvidencedHere": [
            "real systemd suspend/resume with the window open (manual evidence)",
            "wall-clock jump forwards/backwards (needs privileges or faketime)",
            "relay/network reconnect after resume (relay orchestration not implemented yet, A10)",
        ],
        "result": "fail" if failed else "pass",
    }
    write_report(args.report, report)
    if failed:
        raise SystemExit("A18 chaos probe failed: " + ", ".join(failed))
    print("A18 chaos probe: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
