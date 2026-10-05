#!/usr/bin/env python3
"""Deterministic/network-free A05b rusqlite 0.40 API correction gate."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A05B CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
if "DatabaseName" in migration:
    fail("obsolete rusqlite DatabaseName API returned")
for token in (
    'conn.backup("main", &backup, None)?;',
    'conn.restore("main", &backup, None::<fn(rusqlite::backup::Progress)>)?;',
    "forced_migration_failure_restores_existing_v0_profile",
):
    if token not in migration:
        fail("corrected backup/restore contract missing " + token)

sqlite_mod = read("src-tauri/src/infrastructure/sqlite/mod.rs")
if "pub use migration" in sqlite_mod or "pub use repository" in sqlite_mod:
    fail("unused public re-export warnings were reintroduced")
if "pub(crate) mod migration;" not in sqlite_mod or "pub(crate) mod repository;" not in sqlite_mod:
    fail("SQLite modules are not crate-visible for the next adapter stage")

# The previous A05 checker must accept later stages while still validating its own contract.
a05 = read("tools/check_a05.py")
if 'plan.get("stage") != "A05"' in a05:
    fail("A05 checker still freezes the UTS stage")
if 'DatabaseName::Main' in a05:
    fail("A05 checker still requires the obsolete rusqlite API")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("unsupported UTS plan schema")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required in ("a05", "a05b"):
    if required not in ids:
        fail("missing deterministic gate " + required)
if ids.index("a05") >= ids.index("a05b"):
    fail("A05b must follow A05")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A05b rusqlite backup API compile correction" not in status:
    fail("implementation ledger lacks A05b correction")
evidence = read("docs/evidence/A05B_UTS_COMPILE_FIX.md")
for token in ("Fact", "rusqlite 0.40.2", "DatabaseName", '"main"', "UTS", "A06"):
    if token not in evidence:
        fail("A05b evidence missing " + token)

print("A05b rusqlite backup API compile correction: OK")
