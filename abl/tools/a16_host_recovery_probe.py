#!/usr/bin/env python3
"""A16 real-binary backup/doctor/safe-mode/recovery probe.

Runs only CLI/native recovery paths against isolated XDG state. It deliberately
requires no graphical session, D-Bus service, network, root privilege or WebView.
The healthy fixture is created from the checked-in migration SQL and migration
checksum constants so the real binary validates the same schema line it uses in
normal startup.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "src-tauri" / "target" / "debug" / "p2pkanban-arch-native"
MIGRATION_RS = ROOT / "src-tauri" / "src" / "infrastructure" / "sqlite" / "migration.rs"
MIGRATIONS = ROOT / "src-tauri" / "migrations"


def fail(message: str) -> None:
    raise SystemExit("A16 recovery probe failed: " + message)


def isolated_env(base: Path) -> dict[str, str]:
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
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/p2pkanban-a16-bus"
    return env


def run(args: list[str], env: dict[str, str], *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(BINARY), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    if expect_ok and result.returncode != 0:
        fail(f"{' '.join(args)} returned {result.returncode}: {result.stderr.strip()}")
    if not expect_ok and result.returncode == 0:
        fail(f"{' '.join(args)} unexpectedly succeeded")
    return result


def run_json(args: list[str], env: dict[str, str]) -> dict | list:
    result = run(args, env)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"{' '.join(args)} did not emit JSON: {exc}; stdout={result.stdout!r}")


def migration_line() -> list[tuple[str, str]]:
    text = MIGRATION_RS.read_text(encoding="utf-8")
    ids = {
        int(match.group(1)): (int(match.group(2)), match.group(3))
        for match in re.finditer(
            r'pub const MIGRATION_V(\d+)_TO_V(\d+)_ID: &str = "([^"]+)";', text
        )
    }
    hashes = {
        int(match.group(1)): (int(match.group(2)), match.group(3))
        for match in re.finditer(
            r'pub const MIGRATION_V(\d+)_TO_V(\d+)_SHA256: &str = "([0-9a-f]{64})";', text
        )
    }
    if not ids or set(ids) != set(hashes):
        fail("unable to derive migration line from migration.rs")
    line: list[tuple[str, str]] = []
    for source in sorted(ids):
        target, migration_id = ids[source]
        hash_target, checksum = hashes[source]
        if target != hash_target or target != source + 1:
            fail("migration line is not consecutive")
        line.append((migration_id, checksum))
    return line


def seed_healthy_profile(profile: Path) -> None:
    profile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(profile)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            connection.executescript(migration.read_text(encoding="utf-8"))
        for index, (migration_id, checksum) in enumerate(migration_line(), start=1):
            connection.execute(
                "INSERT INTO schema_migrations(id, checksum, applied_at_unix_ms) VALUES (?, ?, ?)",
                (migration_id, checksum, index),
            )
        connection.execute(
            "INSERT INTO workspaces(id, access_epoch, title) VALUES (?, ?, ?)",
            ("a16-workspace", "1", "before-restore"),
        )
        connection.execute(
            "INSERT INTO boards(id, workspace_id, title) VALUES (?, ?, ?)",
            ("a16-board", "a16-workspace", "A16 recovery board"),
        )
        connection.commit()
        connection.execute("PRAGMA journal_mode=WAL").fetchone()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        connection.close()
    os.chmod(profile, 0o600)


def workspace_title(profile: Path) -> str:
    connection = sqlite3.connect(f"file:{profile}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT title FROM workspaces WHERE id='a16-workspace'"
        ).fetchone()
        if row is None:
            fail("A16 workspace disappeared")
        return str(row[0])
    finally:
        connection.close()


def healthy_flow(root: Path) -> dict:
    env = isolated_env(root)
    profile = root / "data" / "p2pkanban" / "profiles" / "default" / "profile.db"
    seed_healthy_profile(profile)

    doctor = run_json(["doctor", "--json"], env)
    if not isinstance(doctor, dict):
        fail("healthy doctor payload is not an object")
    if doctor.get("safeModeRequired") is not False or doctor.get("schemaVersion") != 6:
        fail(f"healthy profile failed doctor: {doctor}")

    manifest = run_json(["backup", "--json"], env)
    if not isinstance(manifest, dict) or manifest.get("format") != "p2pkanban-profile-backup":
        fail(f"manual backup did not return a manifest: {manifest}")
    backup_id = manifest.get("backupId")
    if not isinstance(backup_id, str) or not backup_id.startswith("manual-"):
        fail(f"manual backup id is invalid: {backup_id!r}")

    connection = sqlite3.connect(profile)
    try:
        connection.execute(
            "UPDATE workspaces SET title='after-backup' WHERE id='a16-workspace'"
        )
        connection.commit()
    finally:
        connection.close()
    if workspace_title(profile) != "after-backup":
        fail("mutation before restore was not persisted")

    refused = run(["restore", backup_id, "--json"], env, expect_ok=False)
    if "--yes" not in refused.stderr:
        fail("destructive restore was not refused with explicit confirmation guidance")
    if workspace_title(profile) != "after-backup":
        fail("unconfirmed restore mutated profile")

    restore = run_json(["restore", backup_id, "--yes", "--json"], env)
    if not isinstance(restore, dict) or restore.get("backupId") != backup_id:
        fail(f"restore report drifted: {restore}")
    if restore.get("postRestoreIntegrity") != "ok":
        fail(f"restore post-check did not pass: {restore}")
    if workspace_title(profile) != "before-restore":
        fail("verified restore did not recover the snapshot content")

    backups = run_json(["backups", "--json"], env)
    if not isinstance(backups, list) or not backups:
        fail("verified restore-point list is empty")
    selected = [item for item in backups if item.get("backupId") == backup_id]
    if len(selected) != 1 or selected[0].get("verified") is not True:
        fail(f"manual restore point is not verified in listing: {selected}")
    if not any(str(item.get("backupId", "")).startswith("pre-restore-") for item in backups):
        fail("restore did not preserve a verified pre-restore point for the previous healthy state")

    export_path = root / "a16-recovery-logical.json"
    export_report = run_json(["safe-export", str(export_path), "--json"], env)
    if not isinstance(export_report, dict) or export_report.get("rowCount", 0) < 2:
        fail(f"safe logical export report drifted: {export_report}")
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    if exported.get("format") != "p2pkanban-recovery-logical":
        fail("safe logical export format drifted")
    if "sync_outbox" in exported.get("tables", {}):
        fail("safe logical export leaked operational sync outbox")
    if "sync_outbox" not in exported.get("omittedOperationalState", []):
        fail("safe logical export does not declare omitted operational state")
    workspaces = exported.get("tables", {}).get("workspaces", [])
    if not any(row.get("title") == "before-restore" for row in workspaces):
        fail("safe logical export did not preserve recovered planner content")
    if export_path.stat().st_mode & 0o077:
        fail("safe logical export is not user-private")

    activation = root / "runtime" / "p2pkanban" / "instances" / "default.sock"
    if activation.exists():
        fail("CLI recovery path unexpectedly bound the graphical activation socket")

    return {
        "doctor": {"safeModeRequired": False, "schemaVersion": doctor.get("schemaVersion")},
        "manualBackupId": backup_id,
        "backupVerified": True,
        "restoreConfirmed": True,
        "restoreIntegrity": restore.get("postRestoreIntegrity"),
        "preRestorePointPreserved": True,
        "logicalExportRows": export_report.get("rowCount"),
        "logicalExportOperationalStateOmitted": True,
        "activationSocketBound": False,
    }


def corrupt_flow(root: Path) -> dict:
    env = isolated_env(root)
    fresh = run_json(["doctor", "--json"], env)
    if not isinstance(fresh, dict):
        fail("fresh doctor payload is not an object")
    if fresh.get("profileExists") is not False or fresh.get("safeModeRequired") is not False:
        fail(f"fresh profile doctor drifted: {fresh}")

    profile = root / "data" / "p2pkanban" / "profiles" / "default" / "profile.db"
    profile.write_bytes(b"A16 intentionally corrupt sqlite fixture\n")
    os.chmod(profile, 0o600)
    before = profile.read_bytes()

    corrupt = run_json(["doctor", "--json"], env)
    if not isinstance(corrupt, dict) or corrupt.get("safeModeRequired") is not True:
        fail(f"corrupt profile did not require safe mode: {corrupt}")
    if profile.read_bytes() != before:
        fail("doctor mutated the corrupt profile")

    safe = run_json(["safe-mode", "--json"], env)
    if not isinstance(safe, dict):
        fail("safe-mode payload is not an object")
    expected = {
        "mode": "safe-mode",
        "networkEnabled": False,
        "webviewStarted": False,
        "migrationsEnabled": False,
    }
    for key, value in expected.items():
        if safe.get(key) != value:
            fail(f"safe-mode invariant {key} drifted: {safe.get(key)!r}")
    if safe.get("doctor", {}).get("safeModeRequired") is not True:
        fail("safe-mode did not preserve the doctor failure")
    if profile.read_bytes() != before:
        fail("safe-mode mutated the corrupt profile")

    failed_export = run(["safe-export", str(root / "corrupt-export.json")], env, expect_ok=False)
    if "failed" not in failed_export.stderr.lower():
        fail("corrupt logical export did not fail closed")

    activation = root / "runtime" / "p2pkanban" / "instances" / "default.sock"
    if activation.exists():
        fail("safe-mode unexpectedly bound the graphical activation socket")

    return {
        "freshDoctor": {
            "profileExists": fresh.get("profileExists"),
            "safeModeRequired": fresh.get("safeModeRequired"),
        },
        "corruptDoctor": {
            "safeModeRequired": corrupt.get("safeModeRequired"),
            "schemaVersion": corrupt.get("schemaVersion"),
        },
        "safeMode": expected,
        "corruptProfileUnmodified": True,
        "corruptLogicalExportFailClosed": True,
        "activationSocketBound": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if os.geteuid() == 0:
        fail("normal-use recovery evidence must be collected as a non-root user")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        fail(f"built executable missing or not executable: {BINARY}")

    with tempfile.TemporaryDirectory(prefix="p2pkanban-a16-recovery-") as temp:
        root = Path(temp)
        report = {
            "format": "p2pkanban-a16-host-recovery-probe",
            "healthy": healthy_flow(root / "healthy"),
            "corrupt": corrupt_flow(root / "corrupt"),
        }
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("A16 real-binary backup/doctor/safe-mode/restore probe: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
