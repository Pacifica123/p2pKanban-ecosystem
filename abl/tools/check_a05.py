#!/usr/bin/env python3
"""Deterministic/network-free A05 SQLite profile + migration gate."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A05 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")

required = [
    "src-tauri/src/infrastructure/mod.rs",
    "src-tauri/src/infrastructure/sqlite/mod.rs",
    "src-tauri/src/infrastructure/sqlite/migration.rs",
    "src-tauri/src/infrastructure/sqlite/repository.rs",
    "src-tauri/migrations/0001_initial.sql",
    "docs/evidence/A05_SQLITE_PROFILE.md",
]
for rel in required:
    read(rel)

cargo = read("src-tauri/Cargo.toml")
if 'rusqlite = { version = "=0.40.2", features = ["bundled", "backup"] }' not in cargo:
    fail("rusqlite must be exact-pinned with bundled+backup features")
for token in ("sqlx", "postgres", "diesel", "sea-orm"):
    if token in cargo.lower():
        fail("server/ORM persistence dependency leaked into native Cargo: " + token)

# Application/domain contracts stay database-agnostic even though Cargo now has a SQLite adapter.
for rel in (
    "src-tauri/src/domain/planner.rs",
    "src-tauri/src/application/repository.rs",
    "src-tauri/src/application/repository/contract.rs",
):
    lowered = read(rel).lower()
    for token in ("rusqlite", "sqlite", "sqlx", "pgpool", "postgres"):
        if token in lowered:
            fail(f"persistence implementation leaked into {rel}: {token}")

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
for token in (
    "CURRENT_SCHEMA_VERSION: u32",
    "MIN_READER_SCHEMA_VERSION: u32",
    "MIN_WRITER_SCHEMA_VERSION: u32",
    "BUSY_TIMEOUT_MS: u64 = 2_500",
    '"foreign_keys", "ON"',
    '"synchronous", "FULL"',
    "PRAGMA journal_mode=WAL",
    "PRAGMA integrity_check",
    "pragma_foreign_key_check",
    'conn.backup("main", &backup, None)?;',
    'conn.restore("main", &backup, None::<fn(rusqlite::backup::Progress)>)?;',
    "MIGRATION_V0_TO_V1_ID",
    "MIGRATION_V0_TO_V1_SHA256",
    "schema_migrations",
    "layout.migration_journal()",
    "layout.migration_backup(from)",
    "restored-after-failure",
    "UnsupportedSchema",
):
    if token not in migration:
        fail("migration/durability contract missing " + token)

import hashlib
sql = (ROOT / "src-tauri/migrations/0001_initial.sql").read_bytes()
expected = hashlib.sha256(sql).hexdigest()
match = re.search(r'MIGRATION_V0_TO_V1_SHA256: &str = "([0-9a-f]{64})"', migration)
if not match or match.group(1) != expected:
    fail("migration SQL checksum does not match compiled metadata")
if b"access_epoch TEXT NOT NULL" not in sql or b"logical_clock TEXT NOT NULL" not in sql:
    fail("u64 epoch/clock must not be narrowed to SQLite signed INTEGER")

for test_name in (
    "new_profile_reaches_current_schema_and_durability_pragmas",
    "newer_writer_schema_is_refused",
    "forced_migration_failure_restores_existing_v0_profile",
):
    if test_name not in migration:
        fail("migration test missing " + test_name)

repo = read("src-tauri/src/infrastructure/sqlite/repository.rs")
for token in (
    "impl PlannerRepository for SqlitePlannerRepository",
    "TransactionBehavior::Immediate",
    "current_access_epoch_on(&tx, &transaction.workspace_id)",
    "assert_repository_contract(repo)",
    "assert_stale_epoch_contract(repo)",
    "assert_atomic_rollback_contract(repo)",
    "assert_reorder_contract(repo)",
    "card_survives_close_and_reopen",
):
    if token not in repo:
        fail("SQLite repository contract missing " + token)

# No secret-bearing columns or hard-coded per-user/XDG placement at A05.
combined = (migration + "\n" + repo).lower()
for token in (
    "refresh_token",
    "access_token",
    "private_key",
    "board_key",
    "secret_key",
    "xdg_data_home",
    "xdg_config_home",
    "home/",
    "~/.local",
):
    if token in combined:
        fail("A05 laid incompatible secret/path foundation: " + token)

# A04 checker must permit later adapter dependencies while protecting its source boundary.
a04 = read("tools/check_a04.py")
if "premature persistence dependency" in a04:
    fail("A04 checker still freezes Cargo before A05 adapters")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("unsupported UTS plan schema")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required_id in ("a04", "a04b", "a05"):
    if required_id not in ids:
        fail("missing deterministic gate " + required_id)
if not ids.index("a04") < ids.index("a04b") < ids.index("a05"):
    fail("A05 deterministic gate order is wrong")

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((line for line in status.splitlines() if "A05 SQLite schema + atomic migration engine" in line), "")
if "**implemented" not in line or "A06" not in line:
    fail("implementation ledger did not advance A05 to implemented/A06")
doc = read("docs/evidence/A05_SQLITE_PROFILE.md")
for token in ("Fact", "Inference", "Proposal", "Unresolved", "WAL", "FULL", "A06"):
    if token not in doc:
        fail("A05 evidence document missing " + token)

print("A05 SQLite profile schema + migration engine: OK")
