#!/usr/bin/env python3
"""Deterministic/network-free A07 durable workspace/board + vault-boundary gate."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A07 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


required = (
    "src-tauri/migrations/0002_workspace_board_titles.sql",
    "src-tauri/src/application/workspace.rs",
    "src-tauri/src/application/vault.rs",
    "src-tauri/src/infrastructure/sqlite/workspace.rs",
    "docs/evidence/A07_DURABLE_VERTICAL_SLICE.md",
    "evidence/a07-vertical-slice.json",
)
for rel in required:
    read(rel)

cargo = read("src-tauri/Cargo.toml")
if 'uuid = { version = "=1.26.1", features = ["v4"] }' not in cargo:
    fail("UUID identity generator dependency must be exact-pinned")
for forbidden in ("sqlx", "postgres", "axum"):
    if forbidden in cargo.lower():
        fail("server persistence/runtime dependency leaked into A07 Cargo: " + forbidden)

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
sql2 = (ROOT / "src-tauri/migrations/0002_workspace_board_titles.sql").read_bytes()
expected2 = hashlib.sha256(sql2).hexdigest()
for token in (
    "CURRENT_SCHEMA_VERSION: u32",
    "MIN_READER_SCHEMA_VERSION: u32",
    "MIN_WRITER_SCHEMA_VERSION: u32",
    "MIGRATION_V1_TO_V2_ID",
    "MIGRATION_V1_TO_V2_SHA256",
    "apply_v1_to_v2",
    "v1_profile_migrates_to_v",
    "preserves_workspace_board_identity",
    "forced_migration_failure_restores_existing_v0_profile",
):
    if token not in migration:
        fail("A07 migration contract missing " + token)
for constant in ("CURRENT_SCHEMA_VERSION", "MIN_READER_SCHEMA_VERSION", "MIN_WRITER_SCHEMA_VERSION"):
    parsed = re.search(rf"{constant}: u32 = (\d+)", migration)
    if not parsed or int(parsed.group(1)) < 2:
        fail(constant + " regressed below the A07 schema floor")
match = re.search(r'MIGRATION_V1_TO_V2_SHA256: &str = "([0-9a-f]{64})"', migration)
if not match or match.group(1) != expected2:
    fail("A07 migration SQL checksum does not match compiled metadata")
schema2 = sql2.decode("utf-8")
for token in (
    "ALTER TABLE workspaces ADD COLUMN title TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE boards ADD COLUMN title TEXT NOT NULL DEFAULT ''",
    "schema_version = 2",
    "min_reader = 2",
    "min_writer = 2",
    "PRAGMA user_version = 2",
):
    if token not in schema2:
        fail("schema-v2 compatibility contract missing " + token)

# Application/domain must not know Tauri, SQLite, filesystem, process or network APIs.
for rel in (
    "src-tauri/src/application/workspace.rs",
    "src-tauri/src/application/vault.rs",
    "src-tauri/src/domain/planner.rs",
):
    lowered = read(rel).lower()
    for forbidden in (
        "tauri::", "rusqlite", "sqlite", "sqlx", "pgpool", "postgres",
        "std::fs", "std::net", "std::process", "reqwest", "axum",
    ):
        if forbidden in lowered:
            fail(f"platform/storage token escaped into {rel}: {forbidden}")

workspace = read("src-tauri/src/application/workspace.rs")
for token in (
    "trait WorkspaceCatalogRepository",
    "struct WorkspaceService",
    "struct RandomUuidGenerator",
    "fn list_workspaces",
    "fn create_workspace",
    "fn list_boards",
    "fn create_board",
    "fn open_board",
    "MAX_TITLE_CHARS",
    "application_service_creates_and_opens_board_without_platform_dependencies",
):
    if token not in workspace:
        fail("workspace application contract missing " + token)

vault = read("src-tauri/src/application/vault.rs")
for token in (
    "trait SecretVault",
    "struct SecretValue",
    "struct SessionVault",
    "struct VaultService",
    "VaultMode::SessionOnly",
    "durable: false",
    "self.0.fill(0)",
):
    if token not in vault:
        fail("vault boundary missing " + token)
if re.search(r"#\[derive\([^\]]*Debug[^\]]*\)\]\s*pub struct SecretValue", vault):
    fail("SecretValue must not derive Debug")
for forbidden in ("localstorage", "sessionstorage", "rusqlite", "secret_service::", "zbus::", "kwallet::"):
    if forbidden in vault.lower():
        fail("A07 vault boundary introduced premature or unsafe provider assumption: " + forbidden)

sqlite_workspace = read("src-tauri/src/infrastructure/sqlite/workspace.rs")
for token in (
    "impl WorkspaceCatalogRepository for SqliteWorkspaceCatalog",
    "workspace_and_board_survive_close_and_reopen",
    "board_creation_requires_existing_workspace",
    "sqlite_catalog_schema_has_no_secret_bearing_columns",
    "TransactionBehavior::Immediate",
):
    if token not in sqlite_workspace:
        fail("SQLite workspace catalog contract missing " + token)

# Schema and durable storage must still contain no secret-bearing fields.
schema_all = "\n".join(
    p.read_text(encoding="utf-8").lower()
    for p in sorted((ROOT / "src-tauri/migrations").glob("*.sql"))
)
for forbidden in (
    "refresh_token", "access_token", "board_key", "private_key",
    "vault_root", "secret_key", "password_hash",
):
    if forbidden in schema_all:
        fail("plaintext secret-bearing schema token introduced: " + forbidden)

main = read("src-tauri/src/main.rs")
for token in (
    "instance::acquire(&prepared)",
    "SqliteWorkspaceCatalog::open(&prepared.paths.profile)",
    "WorkspaceService::new(",
    ".manage(workspace_service)",
    ".manage(vault_service)",
    "desktop_api::desktop_api_list_workspaces",
    "desktop_api::desktop_api_create_workspace",
    "desktop_api::desktop_api_list_boards",
    "desktop_api::desktop_api_create_board",
    "desktop_api::desktop_api_open_board",
    "desktop_api::desktop_api_vault_status",
):
    if token not in main:
        fail("A07 composition/allowlist missing " + token)
if "VaultService::session_only()" not in main and "bootstrap_vault(&prepared.paths.profile" not in main:
    fail("A07 vault composition boundary disappeared")
if main.index("instance::acquire(&prepared)") > main.index("SqliteWorkspaceCatalog::open(&prepared.paths.profile)"):
    fail("durable profile opened before A06 single-writer ownership was acquired")

desktop_api = read("src-tauri/src/desktop_api.rs")
desktop_transport = read("src/shared/transport/desktop.ts")
for token in (
    "desktop_api_list_workspaces", "desktop_api_create_workspace",
    "desktop_api_list_boards", "desktop_api_create_board",
    "desktop_api_open_board", "desktop_api_vault_status",
):
    if token not in desktop_api:
        fail("typed Tauri command missing " + token)
for route in (
    "/planner/workspaces", "/planner/boards/list", "/planner/boards",
    "/planner/boards/open", "/system/vault-status",
):
    if route not in desktop_transport:
        fail("desktop transport route missing " + route)
for forbidden in ("desktop_api_put_secret", "desktop_api_get_secret", "desktop_api_delete_secret"):
    if forbidden in (desktop_api + main + desktop_transport):
        fail("secret read/write IPC must not exist in A07: " + forbidden)

frontend = "\n".join(
    p.read_text(encoding="utf-8")
    for p in sorted((ROOT / "src").rglob("*.ts*"))
)
if "localStorage" in frontend or "sessionStorage" in frontend:
    fail("frontend persistence bypass introduced; durable data must stay behind Rust repository boundary")
for token in ("createWorkspace", "createBoard", "openBoard", "getVaultStatus"):
    if token not in frontend:
        fail("A07 frontend vertical slice missing " + token)

# Older gates must protect their own contracts without freezing at A06/schema-v1.
a06 = read("tools/check_a06.py")
if 'plan.get("stage") != "A06"' in a06 or 'exact next architecture patch is **A07' in a06:
    fail("A06 checker still freezes progression at A06/A07")
a05 = read("tools/check_a05.py")
if '"CURRENT_SCHEMA_VERSION: u32 = 1"' in a05:
    fail("A05 checker still freezes the current schema at v1")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("unsupported UTS plan schema")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required_id in ("a06", "a07"):
    if required_id not in ids:
        fail("missing deterministic gate " + required_id)
if ids.index("a06") >= ids.index("a07"):
    fail("A07 deterministic gate must follow A06")

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((line for line in status.splitlines() if "A07 auth/workspace/board minimal offline slice + vault interface" in line), "")
if "**implemented" not in line or "A08" not in line:
    fail("implementation ledger did not advance A07 to implemented/A08")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A08" not in sequence:
    fail("next-patch sequence lost the A08 architecture stage")
adr = read("docs/architecture/adr/ADR-004-secrets.md")
if "A07 established the `SecretVault` application interface" not in adr:
    fail("ADR-004 lost the historical A07 provider-boundary record")

evidence = json.loads(read("evidence/a07-vertical-slice.json"))
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A07":
    fail("A07 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved"):
    if not evidence.get(key):
        fail("A07 evidence classification missing " + key)
current_stage = str(plan.get("stage", ""))
for item in evidence.get("sources", []):
    path = item.get("path")
    digest = item.get("sha256")
    if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
        fail("unsafe A07 evidence source path")
    source_path = ROOT / path
    if not source_path.is_file():
        fail("missing A07 evidence source " + path)
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("invalid historical A07 evidence digest: " + path)
    # The evidence digest binds the exact A07 snapshot. Later architecture stages
    # may evolve shared SSOT/integration files without invalidating A07 semantics.
    if current_stage == "A07":
        actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if digest != actual:
            fail("A07 evidence source digest drifted during A07: " + path)

print("A07 durable workspace/board + vault boundary: OK")
