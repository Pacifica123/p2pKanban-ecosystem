#!/usr/bin/env python3
"""Deterministic/network-free A11 device-link/import migration gate."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A11 CHECK FAILED: " + message)


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
    "src-tauri/migrations/0005_import_link.sql",
    "src-tauri/src/domain/import.rs",
    "src-tauri/src/application/import.rs",
    "src-tauri/src/infrastructure/sqlite/import.rs",
    "docs/evidence/A11_DEVICE_LINK_IMPORT_MIGRATION.md",
    "evidence/a11-device-link-import-migration.json",
]
for rel in required:
    if not (ROOT / rel).is_file():
        fail("missing " + rel)

# A10 resolver prerequisite correction is part of A11, while the final offline
# re-resolution remains mandatory.
cargo = read("src-tauri/Cargo.toml")
if 'serde = { version = "=1.0.228"' not in cargo:
    fail("exact serde 1.0.228 A11 compatibility pin missing")
if 'serde = { version = "=1.0.229"' in cargo:
    fail("obsolete serde 1.0.229 direct pin returned")
for token in [
    'secret-service = { version = "=5.2.0"',
    'getrandom = "=0.4.2"',
    'serde_json = "=1.0.151"',
    'chacha20poly1305 = "=0.10.1"',
]:
    if token not in cargo:
        fail("required exact dependency drifted: " + token)
for forbidden in ("sqlx", "postgres", "axum"):
    if forbidden in cargo.lower():
        fail("backend dependency leaked into native Cargo.toml: " + forbidden)

# Schema v5 is additive metadata only. Secret values must remain outside SQLite.
sql = read("src-tauri/migrations/0005_import_link.sql")
for token in [
    "CREATE TABLE profile_principal",
    "CREATE TABLE import_receipts",
    "CREATE TABLE imported_capability_metadata",
    "CREATE TABLE import_opaque_sections",
    "schema_version = 5",
    "min_reader = 5",
    "min_writer = 5",
    "PRAGMA user_version = 5",
]:
    if token not in sql:
        fail("schema v5 contract missing " + token)
for secret in [
    "board_key",
    "device_private_key",
    "refresh_token",
    "access_token",
    "password_hash",
    "jwt_secret",
    "global_master_key",
    "nostr_signing_secret",
]:
    if secret in sql.lower():
        fail("secret-bearing column/token forbidden in import schema: " + secret)
if sha("src-tauri/migrations/0005_import_link.sql") != "f32f6c68584c4b43c06fd817bb567cce33064fdceb4dd8452f16249679a62726":
    fail("migration 0005 checksum drifted without migration-id correction")

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
for token in [
    "MIGRATION_V4_TO_V5_ID",
    "MIGRATION_V4_TO_V5_SHA256",
    "apply_v4_to_v5",
    "SCHEMA_V5",
]:
    if token not in migration:
        fail("migration engine v5 contract missing " + token)
current_match = re.search(r"CURRENT_SCHEMA_VERSION: u32 = (\d+)", migration)
reader_match = re.search(r"MIN_READER_SCHEMA_VERSION: u32 = (\d+)", migration)
writer_match = re.search(r"MIN_WRITER_SCHEMA_VERSION: u32 = (\d+)", migration)
if not current_match or int(current_match.group(1)) < 5:
    fail("migration engine regressed below A11 schema v5")
if not reader_match or int(reader_match.group(1)) < 5 or not writer_match or int(writer_match.group(1)) < 5:
    fail("reader/writer schema contract regressed below A11")
if "f32f6c68584c4b43c06fd817bb567cce33064fdceb4dd8452f16249679a62726" not in migration:
    fail("migration engine does not lock the exact 0005 checksum")

# Domain contract is storage/runtime independent and keyed to the real legacy
# web/Android protocol identifiers frozen by source anchors.
domain = read("src-tauri/src/domain/import.rs")
for token in [
    'DEVICE_LINK_PROTOCOL_V2: &str = "p2p-kanban-device-link/2"',
    "DEVICE_LINK_GRANT_KIND: u16 = 27_780",
    "DEVICE_LINK_REQUEST_KIND: u16 = 27_781",
    "DEVICE_LINK_RESPONSE_KIND: u16 = 27_782",
    'WEB_NODE_LINK_FORMAT: &str = "p2p-kanban-web-node-link"',
    "WEB_NODE_LINK_VERSION: u32 = 1",
    "WEB_NODE_LINK_MAX_BYTES: usize = 32 * 1024 * 1024",
    'PORTABLE_BUNDLE_FORMAT: &str = "p2p_planner_bundle"',
    "PORTABLE_BUNDLE_VERSION: u32 = 1",
    "parse_device_link_grant_v2",
    "parse_portable_bundle_v1",
    "serialize_portable_bundle_v1",
    "validate_web_node_link_envelope",
    "validate_graph",
    "a11_portable_bundle_roundtrip_preserves_core_and_extensions_without_secrets",
    "a11_portable_archived_at_roundtrip_preserves_exact_value",
    "a11_capability_subject_must_match_native_principal",
]:
    if token not in domain:
        fail("A11 domain compatibility contract missing " + token)
for forbidden in ["rusqlite", "tauri::", "secret_service", "std::fs", "std::net", "reqwest", "TcpStream", "UdpSocket"]:
    if forbidden in domain:
        fail("A11 domain leaked infrastructure capability: " + forbidden)
for secret_key in [
    '"boardkey"',
    '"deviceprivatekey"',
    '"passwordhash"',
    '"jwtsecret"',
    '"globalmasterkey"',
    '"nostrsigningsecret"',
]:
    if secret_key not in domain.lower():
        fail("portable/deployment secret rejection list lost " + secret_key)

app = read("src-tauri/src/application/import.rs")
for token in [
    "pub trait ImportRepository",
    "pub struct ImportService",
    "pub struct DeviceIdentityMaterial",
    "pub struct BoardCapabilityMaterial",
    "SecretKind::DevicePrivateKey",
    "SecretKind::BoardCapability",
    "VaultKeyConflict",
    "provision_authenticated_device_link",
    "import_web_node_link_v1",
    "requires_empty_profile = true",
    "shared-workspaces",
    "node-local-hides",
    "cleanup_vault_writes",
    "plan.receipt.user_id = Some(principal.user_id.clone())",
]:
    if token not in app:
        fail("A11 application boundary missing " + token)
for forbidden in ["rusqlite", "tauri::", "secret_service", "std::fs", "std::net", "reqwest"]:
    if forbidden in app:
        fail("A11 application layer leaked adapter detail: " + forbidden)
# Raw secret wrappers deliberately do not derive Debug/Clone. This blocks easy
# accidental logging/copying while SecretValue zeroizes on drop.
for struct_name in ("DeviceIdentityMaterial", "BoardCapabilityMaterial"):
    match = re.search(rf"(?s)(#\[[^\n]+\]\s*)*pub struct {struct_name}\b", app)
    if not match:
        fail("missing secret wrapper " + struct_name)
    prefix = app[max(0, match.start() - 120):match.start()]
    if "derive(Debug" in prefix or "derive(Clone" in prefix:
        fail(struct_name + " must not derive Debug/Clone")
if "trusted: bool" in app or "trusted=true" in app.lower():
    fail("boolean trust bypass is forbidden in native link provisioning")

# Host Cargo UTS 20260915T073257Z proved two source-level compile defects that
# deterministic checks must prevent from returning: serde_json::Map::entry keys
# must not use an unnecessary `.into()` that leaves the generic target ambiguous,
# and the A09 VaultStatus wire test must initialize/assert the complete status.
for rel in ["src-tauri/src/domain/import.rs", "src-tauri/src/infrastructure/sqlite/sync.rs"]:
    source = read(rel)
    if re.search(r'\.entry\("[^"]+"\.into\(\)\)', source):
        fail("ambiguous serde_json Map::entry key returned in " + rel)
desktop_api_source = read("src-tauri/src/desktop_api.rs")
for token in [
    "VaultStatus::session_only",
    "VaultState::ProviderUnavailable",
    'payload.get("state")',
    'payload.get("passphraseFallbackAvailable")',
    "assert_eq!(payload.len(), 4)",
]:
    if token not in desktop_api_source:
        fail("A09 VaultStatus wire regression test drifted: " + token)

adapter = read("src-tauri/src/infrastructure/sqlite/import.rs")
for token in [
    "SqliteImportRepository",
    "TransactionBehavior::Immediate",
    "import_receipts",
    "profile_principal",
    "imported_capability_metadata",
    "sync_entity_extensions",
    "advance_lamport_floor",
    "a11_portable_bundle_import_is_durable_seed_without_local_outbox",
    "a11_same_source_digest_is_replay_rejected",
    "a11_failed_import_rolls_back_receipt_and_partial_graph",
    "a11_import_schema_has_metadata_but_no_secret_columns",
]:
    if token not in adapter:
        fail("SQLite A11 adapter missing " + token)
if re.search(r"INSERT\s+INTO\s+pending_local_changes", adapter, re.I):
    fail("import must not retransmit restored seed state as local mutations")

# Runtime wires the native service but exposes no generic migration/keyring/file
# Tauri command. The WebView remains presentation-only.
main = read("src-tauri/src/main.rs")
for token in ["ImportService", "SqliteImportRepository", ".manage(import_service)"]:
    if token not in main:
        fail("native runtime did not wire A11 import service: " + token)
desktop_api = read("src-tauri/src/desktop_api.rs")
for forbidden in [
    "SecretValue",
    "DeviceIdentityMaterial",
    "BoardCapabilityMaterial",
    "std::fs",
    "read_to_string",
    "File::open",
    "keyring",
    "secret_service",
]:
    if forbidden in desktop_api:
        fail("WebView IPC gained forbidden secret/filesystem surface: " + forbidden)
capability = load("src-tauri/capabilities/main-minimal.json")
if capability.get("permissions") != []:
    fail("main-minimal WebView permissions must remain empty")
conf = load("src-tauri/tauri.conf.json")
csp = conf.get("app", {}).get("security", {}).get("csp", "")
if "connect-src 'none'" not in csp:
    fail("WebView CSP must keep network disabled")

# Exact frozen source anchors: A11 is derived from the real web/Android contracts,
# not only the synthetic fixtures.
anchors = load("evidence/source-anchors.json")
anchor_map = {(item["source"], item["path"]): item["sha256"] for item in anchors.get("anchors", [])}
expected_anchors = {
    ("web", "backend/src/auth/device_link.rs"): "a1a0dc326efeb32fa883d16559e5ebbec3a1e5982019d039e3d42945ca7b29e1",
    ("web", "backend/src/modules/integrations/dto.rs"): "958788ad02ebd741970705fde8e82ec8abdfd25b4a7b5cbdaf0152669f8a73a3",
    ("web", "backend/src/modules/integrations/service.rs"): "3883142c233fc55980a12a76feb9faa53e2a39ce8f34afa0db2f2d76110f7cd1",
    ("web", "docs/architecture/import-export-backup-v1.md"): "924696575804f06700e1661055cb989fe1cfaab52f9d6ee62897204c280e0383",
    ("web", "docs/architecture/web-node-link-v1.md"): "fbe0925b3a1fa6877d0277c72e58bb27cb5d0bb1106057657738b39959eb3c19",
    ("android", "src/features/deviceLink/protocol.ts"): "3a09b982f866975eeb80d3579258ca6093f2077e911e2012b21e71a074eb4d6b",
    ("android", "src/features/deviceLink/service.ts"): "4858d8447d90dd0833e6417e7e8e4da6bc6c4ca80b0b2833252ce079d84daa3a",
    ("android", "src/features/deviceLink/snapshot.ts"): "e70c73ba2c56fe7399feb34f70885e2db1a7f96e2ac75784271a9ca51a3b9bea",
}
for key, expected in expected_anchors.items():
    if anchor_map.get(key) != expected:
        fail("web/Android source anchor drifted: " + str(key))

fixture = load("fixtures/protocol/device-link-grant-v2.json")
if fixture.get("protocol") != "p2p-kanban-device-link/2" or fixture.get("epoch") != 3:
    fail("A00 device-link/2 grant fixture drifted")
bundle = load("fixtures/export/portable-board-bundle-v1.json")
manifest = bundle.get("manifest.json", {})
if manifest.get("format") != "p2p_planner_bundle" or manifest.get("formatVersion") != 1:
    fail("A00 portable bundle v1 fixture drifted")
if manifest.get("includesLocalMetadata") is not False:
    fail("portable fixture must exclude local metadata")

# Single-entry UTS must now cover A00..A11 while preserving the mandatory
# offline lock/fetch/test/build acceptance.
plan = load("tools/uts_plan.json")
stage = str(plan.get("stage", ""))
stage_match = re.fullmatch(r"A(\d+)", stage)
if plan.get("schemaVersion") != 1 or not stage_match or int(stage_match.group(1)) < 11:
    fail("UTS plan regressed below A11")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a11" not in ids or "a10" not in ids or ids.index("a10") >= ids.index("a11"):
    fail("A11 deterministic gate missing/not ordered after A10")
lock_offline = " ".join(plan.get("cargo", {}).get("lockOffline", []))
fetch_offline = " ".join(plan.get("cargo", {}).get("fetchOffline", []))
test_offline = " ".join(plan.get("cargo", {}).get("test", []))
build_offline = " ".join(plan.get("cargo", {}).get("build", []))
if "generate-lockfile" not in lock_offline or "--offline" not in lock_offline:
    fail("A11 weakened mandatory offline Cargo lock re-resolution")
for name, command in (("fetch", fetch_offline), ("test", test_offline), ("build", build_offline)):
    if "--locked" not in command or "--offline" not in command:
        fail(f"A11 weakened Cargo {name} offline acceptance")
if "allow-yanked" in json.dumps(plan).lower() or "skip-offline" in json.dumps(plan).lower():
    fail("forbidden resolver bypass leaked into UTS plan")
probes = {item.get("id"): " ".join(item.get("command", [])) for item in plan.get("host", {}).get("postBuildProbes", [])}
if "a11-import-compatibility" not in probes or "a11_" not in probes["a11-import-compatibility"]:
    fail("A11 host Cargo compatibility probe missing")
verify = read("tools/uts_verify.py")
for token in [
    "offline_then_optional_network",
    "prepare_cargo_lock",
    "run_deterministic_phase",
    '"cargo.lock.network-fetch"',
    "online_lock = lock_path.read_bytes()",
    "lock_path.unlink()",
    '"cargo.lock.offline-recheck"',
    '"cargo.lock.offline-equivalence"',
    'cargo["fetchNetwork"]',
    "--deterministic-only",
]:
    if token not in verify:
        fail("single-entry UTS strictness drifted: " + token)
if verify.index('"cargo.lock.network-fetch"') > verify.index('"cargo.lock.offline-recheck"'):
    fail("Cargo cache population must happen before mandatory offline lock re-resolution")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A11 device-link/2 + web-node-link/bundle migration" not in status:
    fail("A11 status ledger missing")
next_sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A12" not in next_sequence or (
    "labels/comments/activity/appearance parity" not in next_sequence
    and "## A12 implemented boundary" not in next_sequence
):
    fail("A12 parity sequence provenance missing")
debt = read("docs/architecture/08-implementation-corrections-and-debt.md")
for token in ["CORR-A11-001", "CORR-A11-002", "CORR-A11-003", "serde 1.0.228", "no A10b/A09c", "network-fetch", "DEBT-A11-002", "BEGIN IMMEDIATE"]:
    if token not in debt:
        fail("A11 correction/debt ledger missing " + token)

# Evidence hashes must bind current implementation bytes but may not include the
# evidence file itself (which would be recursively self-hashing).
evidence = load("evidence/a11-device-link-import-migration.json")
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A11":
    fail("A11 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalAnchors", "sources"):
    if not evidence.get(key):
        fail("A11 evidence missing " + key)
for item in evidence.get("sources", []):
    rel = item.get("path", "")
    expected = item.get("sha256", "")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("unsafe A11 evidence source path " + rel)
    path = ROOT / rel
    if not path.is_file():
        fail("missing A11 evidence source " + rel)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid historical A11 evidence digest: " + rel)
    # Historical evidence binds the exact A11 snapshot. Later Axx stages may
    # legitimately evolve shared integration files while A11 semantic guards above
    # remain mandatory. Only demand byte identity while A11 is the current stage.
    if stage == "A11" and sha(rel) != expected:
        fail("A11 evidence source digest drifted during A11: " + rel)

print("A11 device-link/2 + web-node-link/bundle import migration: OK")
