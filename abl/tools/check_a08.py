#!/usr/bin/env python3
"""Deterministic/network-free A08 durable planner slice gate."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A08 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


required = (
    "src-tauri/migrations/0003_planner_slice.sql",
    "src-tauri/src/application/planner.rs",
    "src/features/planner/api/planner.ts",
    "docs/evidence/A08_DURABLE_PLANNER_SLICE.md",
    "evidence/a08-planner-semantics.json",
)
for rel in required:
    read(rel)

# Schema v3 must be exact-addressed and must not become a secret store.
sql_path = ROOT / "src-tauri/migrations/0003_planner_slice.sql"
sql_bytes = sql_path.read_bytes()
sql_digest = hashlib.sha256(sql_bytes).hexdigest()
migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
match = re.search(r'MIGRATION_V2_TO_V3_SHA256: &str = "([0-9a-f]{64})"', migration)
if not match or match.group(1) != sql_digest:
    fail("schema-v3 SQL checksum does not match compiled migration metadata")
for constant in ("CURRENT_SCHEMA_VERSION", "MIN_READER_SCHEMA_VERSION", "MIN_WRITER_SCHEMA_VERSION"):
    parsed = re.search(rf"{constant}: u32 = (\d+)", migration)
    if not parsed or int(parsed.group(1)) < 3:
        fail(constant + " regressed below A08 schema floor 3")
for token in (
    "MIGRATION_V2_TO_V3_ID",
    "apply_v2_to_v3",
    "a08_v2_profile_migrates_to_v3_preserving_existing_planner_identity",
    "forced_migration_failure_restores_existing_v0_profile",
):
    if token not in migration:
        fail("migration-v3 contract missing " + token)

sql = sql_bytes.decode("utf-8")
for token in (
    "ALTER TABLE columns ADD COLUMN title",
    "ALTER TABLE columns ADD COLUMN position",
    "CREATE TABLE checklists",
    "CREATE TABLE checklist_items",
    "CREATE TABLE checklist_tombstones",
    "CREATE TABLE checklist_item_tombstones",
    "CREATE TABLE local_mutation_state",
    "CREATE TABLE pending_local_changes",
    "schema_version = 3",
    "min_reader = 3",
    "min_writer = 3",
    "PRAGMA user_version = 3",
):
    if token not in sql:
        fail("schema-v3 planner contract missing " + token)
for forbidden in (
    "refresh_token", "access_token", "board_key", "private_key", "vault_root",
    "secret_key", "password_hash", "payload BLOB", "payload TEXT",
):
    if forbidden.lower() in sql.lower():
        fail("secret/sync payload leaked into A08 schema: " + forbidden)

# Application/domain remain platform/storage independent.
planner = read("src-tauri/src/application/planner.rs")
domain = read("src-tauri/src/domain/planner.rs")
for rel, text in (("application/planner.rs", planner), ("domain/planner.rs", domain)):
    lowered = text.lower()
    for forbidden in (
        "tauri::", "rusqlite", "sqlite", "sqlx", "pgpool", "postgres",
        "std::fs", "std::net", "std::process", "reqwest", "axum",
    ):
        if forbidden in lowered:
            fail(f"platform/storage token escaped into {rel}: {forbidden}")
for token in (
    "trait PlannerFeatureRepository",
    "struct PlannerService",
    "CreateColumn",
    "CreateChecklist",
    "CreateChecklistItem",
    "SetChecklistItemDone",
    "DeleteChecklist",
    "DeleteChecklistItem",
    "fn create_card",
    "fn move_card",
    "fn swap_card_order",
    "fn set_card_archived",
    "fn delete_card",
    "fn pending_change_count",
    "LOCAL_APPEND_STEP",
):
    if token not in planner:
        fail("A08 application contract missing " + token)
if "const LOCAL_APPEND_STEP: f64 = 1000.0" not in planner:
    fail("A08 local append policy drifted without explicit compatibility review")
for token in (
    "struct ColumnRecord",
    "struct ChecklistRecord",
    "struct ChecklistItemRecord",
    "struct ChecklistTombstone",
    "struct ChecklistItemTombstone",
    "compare_column_order",
    "compare_checklist_order",
    "compare_checklist_item_order",
):
    if token not in domain:
        fail("A08 domain value/order contract missing " + token)

repo = read("src-tauri/src/infrastructure/sqlite/repository.rs")
for token in (
    "impl PlannerFeatureRepository for SqlitePlannerRepository",
    "TransactionBehavior::Immediate",
    "enqueue_pending",
    "next_local_clock",
    "pending_local_changes",
    "a08_planner_slice_survives_close_reopen_and_keeps_pending_explicit",
    "a08_tombstones_block_stale_checklist_and_item_resurrection",
    "a08_forced_abort_rolls_back_card_and_pending_marker_together",
):
    if token not in repo:
        fail("SQLite A08 repository evidence missing " + token)
# Pending markers must still be derived/applied/enqueued inside the same Immediate transaction.
# A10 enriches markers with VersionStamp identity before the mutation; A08 atomicity must remain intact.
for sequence in (
    r"let pending = card_pending_descriptors\(&tx, &mutation\)\?;\s*apply_mutation\(&tx, &transaction\.workspace_id, mutation\)\?;\s*for descriptor in pending \{\s*enqueue_pending\(&tx, &transaction\.workspace_id, &descriptor\)\?;\s*\}",
    r"let pending = feature_pending_descriptors\(&tx, &mutation\)\?;\s*apply_feature_mutation\(&tx, &transaction\.workspace_id, mutation\)\?;\s*for descriptor in pending \{\s*enqueue_pending\(&tx, &transaction\.workspace_id, &descriptor\)\?;\s*\}",
):
    if not re.search(sequence, repo, re.S):
        fail("mutation and pending marker no longer share the expected transaction sequence")

# Explicit IPC/transport only; no generic privileged bridge.
main = read("src-tauri/src/main.rs")
api = read("src-tauri/src/desktop_api.rs")
transport = read("src/shared/transport/desktop.ts")
for command in (
    "desktop_api_list_columns", "desktop_api_create_column", "desktop_api_list_cards",
    "desktop_api_create_card", "desktop_api_move_card", "desktop_api_swap_card_order", "desktop_api_set_card_archived",
    "desktop_api_delete_card", "desktop_api_list_checklists", "desktop_api_create_checklist",
    "desktop_api_delete_checklist", "desktop_api_list_checklist_items",
    "desktop_api_create_checklist_item", "desktop_api_set_checklist_item_done",
    "desktop_api_delete_checklist_item", "desktop_api_pending_change_count",
):
    if command not in main or command not in api or command not in transport:
        fail("explicit A08 IPC command/route missing " + command)
for forbidden in ("plugin:fs", "plugin:shell", "plugin:http", "localhost:", "127.0.0.1"):
    if forbidden in (main + api + transport).lower():
        fail("forbidden privileged/network shortcut introduced: " + forbidden)

frontend = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "src").rglob("*.ts*")))
for forbidden in ("localStorage", "sessionStorage"):
    if forbidden in frontend:
        fail("frontend bypassed Rust durability boundary with " + forbidden)
for token in (
    "createColumn", "createCard", "moveCard", "swapCardOrder", "setCardArchived", "deleteCard",
    "createChecklist", "createChecklistItem", "setChecklistItemDone", "getPendingChangeCount",
):
    if token not in frontend:
        fail("A08 frontend workflow missing " + token)
if "refreshBoard(includeArchived)" not in read("src/App.tsx"):
    fail("show-archived refresh must use the checkbox's new value, not a stale React closure")

# Historical gates must remain valid when the repository advances.
a07 = read("tools/check_a07.py")
a07b = read("tools/check_a07b.py")
if '"v1_profile_migrates_to_v2_and_preserves_workspace_board_identity"' in a07:
    fail("A07 checker still freezes the migration test at schema v2")
if 'plan.get("stage") != "A07b"' in a07b:
    fail("A07b checker still freezes UTS progression at A07b")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("unsupported canonical UTS plan schema")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required_id in ("a07", "a07b", "a08"):
    if required_id not in ids:
        fail("missing deterministic gate " + required_id)
if not (ids.index("a07") < ids.index("a07b") < ids.index("a08")):
    fail("A08 deterministic gate ordering is invalid")
probes = {item.get("id"): item for item in plan.get("host", {}).get("postBuildProbes", [])}
probe = probes.get("a08-planner-durability")
if not probe or "a08_" not in " ".join(probe.get("command", [])):
    fail("canonical UTS plan lacks the filtered A08 Cargo durability probe")

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((line for line in status.splitlines() if "A08 cards/order/archive/delete/checklists durable planner slice" in line), "")
if "implemented" not in line.lower() or "A09" not in line:
    fail("implementation ledger did not advance A08 toward A09")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A09" not in sequence:
    fail("next-patch sequence lost the A09 architecture stage")

# Evidence classifications + local source digests must stay reproducible.
evidence = json.loads(read("evidence/a08-planner-semantics.json"))
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A08":
    fail("A08 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalAnchors"):
    if not evidence.get(key):
        fail("A08 evidence classification missing " + key)
for item in evidence.get("sources", []):
    path = item.get("path")
    digest = item.get("sha256")
    if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
        fail("unsafe A08 evidence source path")
    source = ROOT / path
    if not source.is_file():
        fail("missing A08 evidence source " + path)
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        fail("A08 evidence source digest drifted: " + path)

print("A08 durable planner slice: OK")
