#!/usr/bin/env python3
"""Deterministic/network-free A16 profile recovery boundary gate."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A16 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


def load(rel: str):
    try:
        return json.loads(read(rel))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON {rel}: {exc}")


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


required = [
    "src-tauri/src/domain/recovery.rs",
    "src-tauri/src/application/recovery.rs",
    "src-tauri/src/infrastructure/sqlite/recovery.rs",
    "src-tauri/src/infrastructure/linux/recovery_lock.rs",
    "tools/a16_host_recovery_probe.py",
    "docs/A16_RECOVERY.md",
    "docs/evidence/A16_PROFILE_RECOVERY.md",
    "evidence/a16-profile-recovery.json",
]
for rel in required:
    read(rel)

# A16 is a recovery stage, not a schema/protocol/WebView privilege expansion.
migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
if "CURRENT_SCHEMA_VERSION: u32 = 6" not in migration:
    fail("A16 must not advance schema v6")
if "finalize_existing_snapshot" in migration or "recovery::" in migration:
    fail("A16 must not rewrite the proven A05 migration engine")
capability = load("src-tauri/capabilities/main-minimal.json")
if capability.get("permissions") != []:
    fail("A16 must not grant generic WebView permissions")
conf = load("src-tauri/tauri.conf.json")
if "connect-src 'none'" not in conf.get("app", {}).get("security", {}).get("csp", ""):
    fail("A16 must keep WebView network disabled")

# Domain/application stay storage/platform independent.
domain = read("src-tauri/src/domain/recovery.rs")
for token in (
    "DoctorReport",
    "BackupManifest",
    "BackupSummary",
    "RestoreReport",
    "RecoveryLogicalExport",
    "LogicalExportReport",
    'BACKUP_MANIFEST_FORMAT: &str = "p2pkanban-profile-backup"',
    'RECOVERY_LOGICAL_EXPORT_FORMAT: &str = "p2pkanban-recovery-logical"',
    "valid_backup_id",
):
    if token not in domain:
        fail("A16 domain recovery contract missing " + token)
for forbidden in ("rusqlite", "sqlite", "tauri::", "std::fs", "libc::", "Tcp", "Webview"):
    if forbidden.lower() in domain.lower():
        fail("A16 domain leaked platform/storage detail: " + forbidden)

application = read("src-tauri/src/application/recovery.rs")
for token in (
    "pub trait RecoveryBackend",
    "pub struct RecoveryService",
    "fn doctor(&self)",
    "fn create_manual_backup(&self)",
    "fn create_pre_migration_backup(&self)",
    "fn list_backups(&self)",
    "fn export_logical(&self",
    "fn restore(&self",
    "ExportDestinationExists",
):
    if token not in application:
        fail("A16 application recovery boundary missing " + token)
for forbidden in ("rusqlite", "tauri::", "libc::", "TcpListener", "OpenOptionsExt"):
    if forbidden in application:
        fail("A16 application layer leaked adapter detail: " + forbidden)

linux_lock = read("src-tauri/src/infrastructure/linux/recovery_lock.rs")
for token in (
    "libc::flock",
    "libc::LOCK_EX | libc::LOCK_NB",
    "pub fn acquire(paths: &PreparedDesktopPaths)",
    "a16_recovery_lock_is_exclusive_without_activation_socket",
):
    if token not in linux_lock:
        fail("A16 recovery profile lock missing " + token)
for forbidden in ("UnixDatagram", "activation_socket()", "TcpListener", "UdpSocket"):
    if forbidden == "activation_socket()":
        # It is referenced only in the test to prove absence; production portion must not bind it.
        production = linux_lock.split("#[cfg(test)]", 1)[0]
        if forbidden in production:
            fail("A16 production recovery lock touches graphical activation routing")
    elif forbidden in linux_lock.split("#[cfg(test)]", 1)[0]:
        fail("A16 recovery lock gained a network/activation primitive: " + forbidden)

infra = read("src-tauri/src/infrastructure/sqlite/recovery.rs")
for token in (
    "Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)",
    'source\n        .backup("main", &temporary, None)',
    '"PRAGMA integrity_check"',
    '"SELECT COUNT(*) FROM pragma_foreign_key_check"',
    "database_sha256: sha256_file(path)?",
    "database_bytes: metadata.len()",
    "counts: health.counts",
    "health.counts != manifest.counts",
    "fs::symlink_metadata(&database)",
    "custom_flags(libc::O_NOFOLLOW)",
    "fn build_logical_export",
    "OMITTED_OPERATIONAL_STATE",
    '"sync_outbox"',
    "fn quarantine_current_profile",
    "fn rollback_quarantine",
    '"failed-restored-profile.db"',
    "fn create_pre_migration_backup(&self)",
    '"pre-migration-v{}-to-v{}-{}"',
    "a16_manual_backup_is_verified_and_manifest_bound",
    "a16_corrupt_profile_enters_safe_mode_without_mutation",
    "a16_restore_replaces_profile_and_quarantines_later_state",
    "a16_tampered_restore_point_is_rejected_before_profile_mutation",
    "a16_logical_export_is_read_only_content_salvage_without_operational_state",
    "a16_dangling_profile_symlink_is_not_treated_as_fresh_profile",
    "a16_old_schema_gets_verified_snapshot_before_writable_migration",
):
    # First token intentionally uses an escaped newline; normalize for this structural assertion.
    probe = token.replace("\\n", "\n")
    if probe not in infra:
        fail("A16 SQLite recovery adapter missing " + token)
for forbidden in (
    "fs::copy(self.layout.database()",
    "fs::copy(layout.database()",
    "Command::new",
    "sudo ",
    "pkexec",
    "pacman ",
):
    if forbidden in infra:
        fail("A16 recovery contains forbidden live-copy/privileged behavior: " + forbidden)

# Composition: recovery is parsed before graphical probes and preflight precedes writable repositories.
main = read("src-tauri/src/main.rs")
for token in (
    "RecoveryCliCommand",
    '"doctor"',
    '"backup"',
    '"backups"',
    '"safe-mode"',
    '"safe-export"',
    '"restore"',
    "recovery_lock::acquire(prepared)",
    '"networkEnabled": false',
    '"webviewStarted": false',
    '"migrationsEnabled": false',
    '"restore is destructive; rerun with --yes',
    "create_pre_migration_backup()",
    "profile requires recovery; run `p2pkanban safe-mode`",
):
    if token not in main:
        fail("A16 runtime composition missing " + token)
recovery_fn = main[main.index("fn run_recovery_cli("):main.index("fn startup_deep_link()")]
for forbidden in ("tauri::Builder", "WebviewWindowBuilder", "LinuxLanBridgeRuntime::production", "instance::acquire("):
    if forbidden in recovery_fn:
        fail("A16 CLI recovery unexpectedly starts graphical/network composition: " + forbidden)
if main.index("if let Some(command) = recovery_command") > main.index("instance::acquire(&prepared)"):
    fail("A16 CLI recovery is not dispatched before normal graphical instance ownership")
if main.index("recovery_report.safe_mode_required") > main.index("SqliteWorkspaceCatalog::open(&prepared.paths.profile)"):
    fail("A16 doctor preflight occurs after writable profile open")
if main.index("create_pre_migration_backup()") > main.index("SqliteWorkspaceCatalog::open(&prepared.paths.profile)"):
    fail("A16 verified pre-migration snapshot occurs after writable migration can start")

# Host evidence must exercise behavior, not just source greps.
host_probe = read("tools/a16_host_recovery_probe.py")
for token in (
    "seed_healthy_profile",
    '["doctor", "--json"]',
    '["backup", "--json"]',
    '["restore", backup_id, "--json"]',
    '["restore", backup_id, "--yes", "--json"]',
    '["backups", "--json"]',
    '["safe-export", str(export_path), "--json"]',
    '["safe-mode", "--json"]',
    "pre-restore-",
    "corruptProfileUnmodified",
    "activationSocketBound",
):
    if token not in host_probe:
        fail("A16 real-binary host probe missing " + token)
for forbidden in ("sudo", "pacman -S", "pkexec", "curl", "wget", "requests"):
    if forbidden in host_probe:
        fail("A16 host probe performs forbidden bootstrap/privileged behavior: " + forbidden)

plan = load("tools/uts_plan.json")
if plan.get("schemaVersion") != 1 or int(str(plan.get("stage", "A0")).removeprefix("A")) < 16:
    fail("UTS plan did not advance to A16")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if not {"a15", "a16"}.issubset(ids) or ids.index("a15") >= ids.index("a16"):
    fail("A16 deterministic gate missing/not ordered after A15")
post = {item.get("id"): item.get("command") for item in plan.get("host", {}).get("postBuildProbes", [])}
if post.get("a16-rust-recovery") != [
    "cargo", "test", "--manifest-path", "src-tauri/Cargo.toml", "--locked", "--offline", "a16_", "--", "--nocapture"
]:
    fail("A16 Rust recovery test probe missing from canonical UTS")
if post.get("a16-host-recovery") != [
    "python3", "-B", "tools/a16_host_recovery_probe.py", "--report", "{report_dir}/a16-recovery.json"
]:
    fail("A16 real-binary recovery probe missing from canonical UTS")
manual = "\n".join(plan.get("manualEvidence", []))
for token in (
    "A16 CLI recovery",
    "A16 backup/restore",
    "A16 migration recovery",
    "A16 logical salvage",
    "A16 failure containment",
):
    if token not in manual:
        fail("A16 manual acceptance contract missing " + token)

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A16 backup/doctor/safe-mode/recovery" not in status:
    fail("A16 implementation ledger missing")
if "canonical Cargo + real-binary recovery UTS pending" not in status:
    fail("A16 ledger prematurely claims host acceptance")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A16 implemented boundary" not in sequence or "A17 — AppImage fallback + offline release kit" not in sequence:
    fail("post-A16 next-stage sequence is not A17")
debt = read("docs/architecture/08-implementation-corrections-and-debt.md")
for token in ("DEBT-A16-001", "DEBT-A16-002", "DEBT-A16-003"):
    if token not in debt:
        fail("A16 debt ledger missing " + token)

# Evidence binds A16-owned files. Shared status/UTS/docs may evolve after A16.
evidence = load("evidence/a16-profile-recovery.json")
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A16":
    fail("A16 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalReferences", "sources"):
    if not evidence.get(key):
        fail("A16 evidence missing " + key)
for item in evidence.get("sources", []):
    rel = item.get("path", "")
    expected = item.get("sha256", "")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("unsafe A16 evidence source path " + rel)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid A16 evidence digest " + rel)
    if not (ROOT / rel).is_file() or sha(rel) != expected:
        fail("A16 evidence source digest drifted: " + rel)

print("A16 verified profile backup/doctor/safe-mode/recovery boundary: OK")
