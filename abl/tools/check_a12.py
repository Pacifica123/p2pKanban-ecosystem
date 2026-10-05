#!/usr/bin/env python3
"""Deterministic/network-free A12 parity-surface gate."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A12 CHECK FAILED: " + message)


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
    "src-tauri/migrations/0006_parity_surface.sql",
    "src-tauri/src/domain/parity.rs",
    "src-tauri/src/application/parity.rs",
    "src-tauri/src/infrastructure/sqlite/parity.rs",
    "src/features/parity/api/parity.ts",
    "fixtures/export/portable-board-bundle-v1-parity.json",
    "docs/evidence/A12_PARITY_SURFACE.md",
    "evidence/a12-parity-surface.json",
]
for rel in required:
    if not (ROOT / rel).is_file():
        fail("missing " + rel)

sql = read("src-tauri/migrations/0006_parity_surface.sql")
for token in [
    "CREATE TABLE labels",
    "CREATE TABLE card_labels",
    "CREATE TABLE comments",
    "CREATE TABLE board_appearance_settings",
    "CREATE TABLE activity_entries",
    "CREATE TABLE parity_local_changes",
    "reason = 'roaming-v1-unsupported'",
    "schema_version = 6",
    "min_reader = 6",
    "min_writer = 6",
    "PRAGMA user_version = 6",
]:
    if token not in sql:
        fail("schema v6 parity contract missing " + token)
if "card_id TEXT REFERENCES cards" in sql:
    fail("activity card_id must remain provenance text, not cascade with card deletion")
for forbidden in ["board_key", "refresh_token", "access_token", "password_hash", "jwt_secret", "private_key"]:
    if forbidden in sql.lower():
        fail("secret-bearing column/token forbidden in parity schema: " + forbidden)
expected_migration_sha = "b753e298b520e05b493c1e06b3801ea0b528d42635756f8ae0ca2e38e4adac8a"
if sha("src-tauri/migrations/0006_parity_surface.sql") != expected_migration_sha:
    fail("migration 0006 checksum drifted")

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
for token in [
    "CURRENT_SCHEMA_VERSION: u32 = 6",
    "MIN_READER_SCHEMA_VERSION: u32 = 6",
    "MIN_WRITER_SCHEMA_VERSION: u32 = 6",
    'MIGRATION_V5_TO_V6_ID: &str = "desktop-0006-parity-surface"',
    expected_migration_sha,
    "apply_v5_to_v6",
    "SCHEMA_V6",
]:
    if token not in migration:
        fail("migration engine v6 contract missing " + token)

# Domain/application remain storage/runtime independent.
domain = read("src-tauri/src/domain/parity.rs")
for token in ["LabelId", "CommentId", "ActivityEntryId", "LabelRecord", "CardLabelRecord", "CommentRecord", "BoardAppearanceRecord", "ActivityEntryRecord"]:
    if token not in domain:
        fail("parity domain missing " + token)
for forbidden in ["rusqlite", "tauri::", "secret_service", "std::fs", "reqwest"]:
    if forbidden in domain:
        fail("parity domain leaked infrastructure capability: " + forbidden)

app = read("src-tauri/src/application/parity.rs")
for token in [
    "pub trait ParityRepository",
    "pub struct ParityService",
    "create_label",
    "set_card_label",
    "create_comment",
    "set_appearance",
    "list_activity",
    "unsynced_parity_count",
    "MAX_LABEL_CHARS",
    "MAX_COMMENT_CHARS",
    "MAX_APPEARANCE_BYTES",
]:
    if token not in app:
        fail("A12 application contract missing " + token)
for forbidden in ["rusqlite", "tauri::", "secret_service", "std::fs", "reqwest"]:
    if forbidden in app:
        fail("A12 application layer leaked adapter detail: " + forbidden)
# Result<()> service methods must return an explicit successful result after repository calls.
for method in ["delete_label", "set_card_label", "delete_comment"]:
    match = re.search(rf"pub fn {method}\b(?s:.*?)\n    }}", app)
    if not match or "Ok(())" not in match.group(0):
        fail(method + " does not close its application Result contract explicitly")

adapter = read("src-tauri/src/infrastructure/sqlite/parity.rs")
for token in [
    "SqliteParityRepository",
    "TransactionBehavior::Immediate",
    "parity_local_changes",
    "roaming-v1-unsupported",
    "pending_local_changes",
    '"board.appearance.put"',
    "insert_activity",
    "a12_local_label_comment_activity_are_atomic_and_explicitly_unsynced",
    "a12_appearance_is_durable_and_uses_existing_roaming_pending_kind",
]:
    if token not in adapter:
        fail("SQLite A12 adapter missing " + token)
if "DELETE FROM activity_entries" in adapter:
    fail("local entity deletion must not erase provenance activity")

# Labels/comments stay explicit local parity until roaming/1 actually defines operations.
sync = read("src-tauri/src/infrastructure/sqlite/sync.rs")
for token in [
    "fn appearance_payload",
    '"board.appearance.put" => Ok(vec![event(',
    'json!({"appearance": appearance_payload',
    "fn apply_board_appearance",
    "a12_appearance_pending_materializes_and_remote_apply_persists",
]:
    if token not in sync:
        fail("A12 appearance sync mapping missing " + token)
for invented in ['"label.put"', '"label.delete"', '"comment.put"', '"comment.delete"']:
    if invented in sync:
        fail("invented roaming/1 operation leaked into sync core: " + invented)

import_adapter = read("src-tauri/src/infrastructure/sqlite/import.rs")
for token in [
    "fn materialize_parity_sections",
    'section_array(plan, "labels")',
    'section_array(plan, "cardLabels")',
    'section_array(plan, "comments")',
    'section_array(plan, "boardAppearanceSettings")',
    'section_array(plan, "activityEntries")',
    "a12_portable_parity_sections_materialize_without_local_mutation_markers",
    "a12_import_rejects_fabricated_activity_provenance",
    "SELECT COUNT(*) FROM parity_local_changes",
]:
    if token not in import_adapter:
        fail("A11→A12 parity materialization missing " + token)
if "now_rfc3339" in import_adapter or "legacy.imported" in import_adapter:
    fail("A12 import must not fabricate activity chronology/kind")
# CORR-A12-001: parsed opaque-section JSON is local to section_array; never return
# references into that temporary Value. Keep the materialization helper owned.
if "Result<Vec<Map<String, Value>>, ImportRepositoryError>" not in import_adapter or ".as_object().cloned()" not in import_adapter:
    fail("CORR-A12-001 owned opaque-section materialization regressed")
if "Result<Vec<&" in import_adapter and "fn section_array" in import_adapter:
    fail("CORR-A12-001 section_array must not return references into parsed local JSON")

fixture = load("fixtures/export/portable-board-bundle-v1-parity.json")
payload = fixture.get("payload", {})
if fixture.get("manifest.json", {}).get("format") != "p2p_planner_bundle":
    fail("A12 portable fixture lost bundle format")
for key in ["labels", "cardLabels", "comments", "boardAppearanceSettings", "activityEntries"]:
    if not isinstance(payload.get(key), list) or len(payload[key]) != 1:
        fail("A12 portable fixture does not exercise " + key)
if fixture.get("manifest.json", {}).get("includesLocalMetadata") is not False:
    fail("A12 portable fixture must not promote local metadata")

# IPC is typed and bounded; there is still no generic filesystem/keyring/secret command.
main = read("src-tauri/src/main.rs")
for token in ["ParityService", "SqliteParityRepository", ".manage(parity_service)", "desktop_api::desktop_api_list_labels", "desktop_api::desktop_api_set_appearance"]:
    if token not in main:
        fail("native runtime did not wire A12 parity boundary: " + token)
desktop_api = read("src-tauri/src/desktop_api.rs")
for token in ["desktop_api_create_label", "desktop_api_set_card_label", "desktop_api_create_comment", "desktop_api_set_appearance", "desktop_api_list_activity", "desktop_api_unsynced_parity_count"]:
    if token not in desktop_api:
        fail("typed A12 command missing " + token)
for forbidden in ["std::fs", "read_to_string", "File::open", "keyring", "secret_service", "SecretValue"]:
    if forbidden in desktop_api:
        fail("A12 WebView IPC gained forbidden generic privilege: " + forbidden)
capability = load("src-tauri/capabilities/main-minimal.json")
if capability.get("permissions") != []:
    fail("A12 must keep WebView permissions empty")
conf = load("src-tauri/tauri.conf.json")
if "connect-src 'none'" not in conf.get("app", {}).get("security", {}).get("csp", ""):
    fail("A12 must keep WebView network disabled")

frontend_api = read("src/features/parity/api/parity.ts")
transport = read("src/shared/transport/desktop.ts")
ui = read("src/App.tsx")
current_plan = load("tools/uts_plan.json")
current_stage = str(current_plan.get("stage", ""))
stage_match = re.fullmatch(r"A(\d+)", current_stage)
if not stage_match or int(stage_match.group(1)) < 12:
    fail("UTS plan regressed below A12")
for path in ["/parity/labels/list", "/parity/card-labels/set", "/parity/comments/list", "/parity/appearance/set", "/parity/activity/list", "/parity/unsynced-count"]:
    if path not in frontend_api or path not in transport:
        fail("typed desktop parity route missing " + path)
ui_tokens = ["roaming/1 unsupported parity changes", "Local provenance", "Board appearance JSON", "local durable comment"]
if current_stage == "A12":
    ui_tokens.insert(0, "A12 PARITY SURFACE")
for token in ui_tokens:
    if token not in ui:
        fail("A12 UI parity surface missing " + token)

# Frozen A00 evidence establishes the only wire claim A12 makes: appearance exists
# in roaming snapshot/operations. Label/comment roaming ops remain intentionally absent.
anchors = load("evidence/source-anchors.json")
anchor_map = {(item["source"], item["path"]): item["sha256"] for item in anchors.get("anchors", [])}
expected_anchors = {
    ("web", "docs/sync/roaming-board-protocol-v1.md"): "f50d1cb334b8f991d89a39794b60f6f931da5302027b31c48ca9850bd9a46841",
    ("android", "src/features/roaming/types.ts"): "cfd1004962a38ad07913b7d8de5986d4d28087af4540967989ccf56c4a807665",
    ("android", "src/features/roaming/service.ts"): "282b00bdc89965d8734ce5f697102d10170f3fca6b748ead1b18435ffda9a223",
}
for key, expected in expected_anchors.items():
    if anchor_map.get(key) != expected:
        fail("A12 source anchor drifted: " + str(key))
snapshot = load("fixtures/protocol/roaming-board-snapshot-v1.json")
if snapshot.get("operation") != "board.snapshot":
    fail("roaming snapshot fixture drifted")
appearance = snapshot.get("payload", {}).get("snapshot", {}).get("appearance")
if not isinstance(appearance, dict) or appearance.get("boardId") != snapshot.get("boardId"):
    fail("roaming appearance fixture contract drifted")

plan = current_plan
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema regressed after A12")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a11" not in ids or "a12" not in ids or ids.index("a11") >= ids.index("a12"):
    fail("A12 deterministic gate missing/not ordered after A11")
probes = {item.get("id"): " ".join(item.get("command", [])) for item in plan.get("host", {}).get("postBuildProbes", [])}
if "a12-parity-compatibility" not in probes or "a12_" not in probes["a12-parity-compatibility"]:
    fail("A12 host Cargo parity probe missing")
verify = read("tools/uts_verify.py")
if "--deterministic-only" not in verify or "postbuild.deterministic" not in verify:
    fail("canonical UTS strictness regressed")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A12 labels/comments/activity/appearance parity" not in status:
    fail("A12 status ledger missing")
if current_stage == "A12" and "canonical UTS pending" not in status:
    fail("A12 status ledger prematurely claims acceptance")
if current_stage != "A12" and "canonical UTS green" not in status:
    fail("later stage must preserve A12 canonical UTS-green provenance")
next_sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if current_stage == "A12":
    if "A13" not in next_sequence or "lifecycle/integration capability detection" not in next_sequence:
        fail("next stage after A12 is not A13 lifecycle/integration")
else:
    if "A12 implemented boundary" not in next_sequence:
        fail("post-A12 sequence lost the implemented A12 boundary")
debt = read("docs/architecture/08-implementation-corrections-and-debt.md")
for token in ["DEBT-A12-001", "roaming-v1-unsupported", "DEBT-A12-002", "payload.appearance", "CORR-A12-001", "E0515"]:
    if token not in debt:
        fail("A12 parity/debt ledger missing " + token)

# Evidence hashes bind the exact A12 implementation while A12 is current. Future
# stages may evolve shared integration files, but the semantic guards above stay live.
evidence = load("evidence/a12-parity-surface.json")
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A12":
    fail("A12 evidence metadata mismatch")
for key in ["facts", "inferences", "proposals", "unresolved", "externalAnchors", "sources"]:
    if not evidence.get(key):
        fail("A12 evidence missing " + key)
evolving_after_a12 = {
    "src-tauri/src/desktop_api.rs",
    "src-tauri/src/main.rs",
    "src/shared/transport/desktop.ts",
    "src/shared/api/types.ts",
    "src/App.tsx",
    "src/styles.css",
    "tools/check_a12.py",
    "tools/uts_plan.json",
    "docs/architecture/08-implementation-corrections-and-debt.md",
    "docs/IMPLEMENTATION_STATUS.md",
}
for item in evidence.get("sources", []):
    rel = item.get("path", "")
    expected = item.get("sha256", "")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("unsafe A12 evidence source path " + rel)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid A12 evidence digest " + rel)
    if not (ROOT / rel).is_file():
        fail("missing A12 evidence source " + rel)
    if current_plan.get("stage") != "A12" and rel in evolving_after_a12:
        continue
    if sha(rel) != expected:
        fail("A12 evidence source digest drifted: " + rel)

print("A12 labels/comments/activity/appearance parity: OK")
