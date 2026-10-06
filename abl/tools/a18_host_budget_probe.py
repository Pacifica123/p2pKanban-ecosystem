#!/usr/bin/env python3
"""A18 measured budgets: startup, idle memory/CPU/wakeups, disk, CLI latency.

    a18_host_budget_probe.py profile-scale [--profile debug|release] [--report R]
    a18_host_budget_probe.py runtime       [--profile debug|release] [--report R] [--idle-seconds N]
    a18_host_budget_probe.py all           ...

profile-scale needs no display: it seeds the packaging/budgets fixture
(10k cards, 100k pending changes) through the checked-in migration line and
times the real binary's doctor/backup. runtime launches the real GUI twice
(empty profile, fixture profile) in isolated XDG directories and samples the
whole process tree from /proc.

Budgets come from packaging/budgets/a18-budgets.json. While its status is
"proposed", numeric overruns are reported but do not fail the run; invariants
(no inet sockets, nothing left running after exit, startup settles) always do.
`--enforce`, or status "accepted", makes every overrun fail. A debug build is
judged against limits multiplied by debugAllowance and is only indicative;
Gate G evidence is a release-profile run.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from a18_common import (
    App, binary_path, dir_kib, evaluate, isolated_env, load_budgets, profile_db,
    require_display, require_session, run_cli, write_report,
)
from a16_host_recovery_probe import MIGRATIONS, migration_line


def fail(message: str) -> None:
    raise SystemExit("A18 budget probe failed: " + message)


def seed_fixture(db: Path, fixture: dict[str, int]) -> dict[str, int]:
    """Schema from the real migration SQL + checksums; rows are deterministic."""
    db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            conn.executescript(migration.read_text(encoding="utf-8"))
        for index, (migration_id, checksum) in enumerate(migration_line(), start=1):
            conn.execute("INSERT INTO schema_migrations(id, checksum, applied_at_unix_ms) VALUES (?, ?, ?)",
                         (migration_id, checksum, index))
        ws, board = "a18-workspace", "a18-board"
        conn.execute("INSERT INTO workspaces(id, access_epoch, title) VALUES (?, '1', 'A18 scale')", (ws,))
        conn.execute("INSERT INTO boards(id, workspace_id, title) VALUES (?, ?, 'A18 scale board')", (board, ws))
        columns = [f"a18-column-{i:02d}" for i in range(fixture["columns"])]
        conn.executemany("INSERT INTO columns(id, board_id, title, position) VALUES (?, ?, ?, ?)",
                         [(c, board, f"Колонка {i}", (i + 1) * 1024.0) for i, c in enumerate(columns)])
        conn.executemany(
            "INSERT INTO cards(id, workspace_id, board_id, column_id, title, position, lifecycle) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(f"a18-card-{i:06d}", ws, board, columns[i % len(columns)],
              f"Карточка {i}: проверка масштаба профиля A18", (i // len(columns) + 1) * 1024.0,
              "archived" if i % 10 == 9 else "active") for i in range(fixture["cards"])])
        conn.executemany(
            "INSERT INTO checklists(id, workspace_id, board_id, card_id, title, position) VALUES (?, ?, ?, ?, ?, ?)",
            [(f"a18-checklist-{i:06d}", ws, board, f"a18-card-{i % fixture['cards']:06d}", f"Список {i}", 1024.0)
             for i in range(fixture["checklists"])])
        conn.executemany(
            "INSERT INTO checklist_items(id, checklist_id, title, position, is_done) VALUES (?, ?, ?, ?, ?)",
            [(f"a18-item-{i:06d}", f"a18-checklist-{i % fixture['checklists']:06d}", f"Пункт {i}",
              (i // fixture["checklists"] + 1) * 1024.0, i % 2) for i in range(fixture["checklistItems"])])
        conn.executemany(
            "INSERT INTO pending_local_changes(id, workspace_id, board_id, sequence, kind, entity_id, created_at_unix_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(f"a18-pending-{i:07d}", ws, board, f"{i + 1:020d}", "card.update",
              f"a18-card-{i % fixture['cards']:06d}", 1_700_000_000_000 + i)
             for i in range(fixture["pendingLocalChanges"])])
        conn.commit()
        conn.execute("PRAGMA journal_mode=WAL").fetchone()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("columns", "cards", "checklists", "checklist_items", "pending_local_changes")}
    finally:
        conn.close()
    os.chmod(db, 0o600)
    return counts


def profile_scale(binary: Path, budgets: dict, work: Path) -> dict[str, object]:
    base = work / "profile-scale"
    env = isolated_env(base, keep_display=False)
    db = profile_db(base)
    start = time.monotonic()
    counts = seed_fixture(db, budgets["fixture"])
    seed_ms = round((time.monotonic() - start) * 1000)
    db_kib = sum(p.stat().st_size for p in db.parent.glob("profile.db*")) // 1024

    doctor, doctor_ms = run_cli(binary, ["doctor", "--json"], env)
    if doctor.returncode != 0:
        fail(f"doctor on the fixture returned {doctor.returncode}: {doctor.stderr.strip()}")
    report = json.loads(doctor.stdout)
    if report.get("safeModeRequired") is not False or report.get("schemaVersion") != 6:
        fail(f"fixture profile is not healthy for the real binary: {report}")

    backup, backup_ms = run_cli(binary, ["backup", "--json"], env)
    if backup.returncode != 0:
        fail(f"backup on the fixture returned {backup.returncode}: {backup.stderr.strip()}")
    manifest = json.loads(backup.stdout)
    backup_kib = dir_kib(db.parent / "backups")
    return {
        "fixtureCounts": counts,
        "seedMs": seed_ms,
        "fixtureProfileMiB": round(db_kib / 1024, 2),
        "doctorMs": doctor_ms,
        "backupMs": backup_ms,
        "backupMiB": round(backup_kib / 1024, 2),
        "backupId": manifest.get("backupId"),
        "method": "wall clock around one real-binary CLI invocation each; fixture seeded through migration SQL",
    }


def runtime_once(binary: Path, budgets: dict, work: Path, name: str, seeded: bool,
                 idle_seconds: float, log_dir: Path) -> dict[str, object]:
    base = work / name
    env = isolated_env(base)
    if seeded:
        seed_fixture(profile_db(base), budgets["fixture"])
    app = App(binary, env, log_dir, name)
    try:
        settle_ms = app.wait_settled(timeout=60)
        idle = app.idle_window(idle_seconds)
    except RuntimeError as exc:
        app.kill()
        fail(f"{name}: {exc}; see {app.stderr_path}")
    xdg_kib = sum(dir_kib(base / part) for part in ("config", "data", "cache", "state"))
    leftover = app.stop()
    return {
        "startupSettleMs": settle_ms,
        "webProcessSeen": app.web_process_seen,
        **idle,
        "xdgFootprintMiB": round(xdg_kib / 1024, 2),
        "processesAfterExit": leftover,
        "method": "startup = spawn until tree CPU < 5% of one core for 0.5 s after the WebKit web process exists; "
                  "CPU from /proc/<pid>/stat utime+stime; wakeups = all-thread context switches/s (proxy); "
                  "memory = sum of smaps_rollup Pss; exit = SIGTERM to the main process, survivors after 5 s",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["profile-scale", "runtime", "all"])
    parser.add_argument("--profile", choices=["debug", "release"], default="debug")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--idle-seconds", type=float)
    parser.add_argument("--enforce", action="store_true", help="fail on any numeric overrun (Gate G)")
    args = parser.parse_args()

    budgets = load_budgets()
    binary = binary_path(args.profile)
    require_session(binary)
    if args.command in {"runtime", "all"}:
        require_display()
    idle_seconds = args.idle_seconds or float(budgets.get("idleWindowSeconds", 30))
    log_dir = (args.report.parent if args.report else Path(tempfile.gettempdir())) / "a18-app-logs"

    measured: dict[str, dict[str, object]] = {}
    with tempfile.TemporaryDirectory(prefix="p2pkanban-a18-budget-") as temp:
        work = Path(temp)
        if args.command in {"profile-scale", "all"}:
            measured["profile-scale"] = profile_scale(binary, budgets, work)
        if args.command in {"runtime", "all"}:
            measured["runtime-empty"] = runtime_once(binary, budgets, work, "runtime-empty", False, idle_seconds, log_dir)
            measured["runtime-fixture"] = runtime_once(binary, budgets, work, "runtime-fixture", True, idle_seconds, log_dir)

    scenarios = set(measured)
    rows = [row for row in evaluate(budgets, measured, args.profile) if row["scenario"] in scenarios]
    enforce = args.enforce or budgets["status"] == "accepted"
    broken = [r for r in rows if r["verdict"] == "over" and (enforce or r["kind"] == "invariant")]
    unmeasured = [r for r in rows if r["verdict"] == "unmeasured"]
    report = {
        "format": "p2pkanban-a18-budget-probe",
        "command": args.command,
        "buildProfile": args.profile,
        "binary": str(binary),
        "indicativeOnly": args.profile == "debug",
        "budgetsStatus": budgets["status"],
        "enforced": enforce,
        "measured": measured,
        "budgets": rows,
        "result": "fail" if broken or unmeasured else "pass",
    }
    write_report(args.report, report)
    width = max(len(r["id"]) for r in rows) if rows else 0
    for r in rows:
        print(f"{r['verdict']:>18}  {r['id']:<{width}}  {r['value']} / {r['limit']} {r['unit']}")
    over = [r for r in rows if r["verdict"] == "over"]
    print(f"A18 budgets ({args.profile}, {budgets['status']}{', enforced' if enforce else ''}): "
          f"{len(rows) - len(over) - len(unmeasured)} within or accepted, {len(over)} over, {len(unmeasured)} unmeasured")
    if broken or unmeasured:
        fail("; ".join(f"{r['id']}={r['value']} > {r['limit']}" for r in broken)
             + ("; unmeasured: " + ", ".join(r["id"] for r in unmeasured) if unmeasured else ""))
    print("A18 budget probe: PASS" + (" (overruns reported, not enforced while budgets are proposed)" if over else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
