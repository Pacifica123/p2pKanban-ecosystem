#!/usr/bin/env python3
"""Deterministic/network-free A03 application/domain boundary gate."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A03 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


required = [
    "src-tauri/src/application/mod.rs",
    "src-tauri/src/application/system.rs",
    "src-tauri/src/domain/mod.rs",
    "src-tauri/src/domain/system.rs",
    "docs/evidence/A03_APPLICATION_DOMAIN_BOUNDARY.md",
]
for rel in required:
    read(rel)

core_paths = sorted((ROOT / "src-tauri/src/application").rglob("*.rs")) + sorted(
    (ROOT / "src-tauri/src/domain").rglob("*.rs")
)
if not core_paths:
    fail("application/domain source set is empty")

forbidden_core_tokens = (
    "tauri::",
    "#[tauri::",
    "axum",
    "sqlx",
    "PgPool",
    "Postgres",
    "postgres://",
    "postgresql://",
    "rusqlite",
    "sqlite",
    "reqwest",
    "hyper::",
    "std::fs",
    "std::net",
    "std::process",
    "TcpListener",
    "UdpSocket",
    "Command::new",
)
for path in core_paths:
    text = path.read_text(encoding="utf-8")
    for token in forbidden_core_tokens:
        if token.lower() in text.lower():
            fail(f"platform/storage token escaped into core: {token} in {path.relative_to(ROOT)}")

application = read("src-tauri/src/application/mod.rs") + "\n" + read("src-tauri/src/application/system.rs")
for token in ("ApplicationServices", "SystemService", "HealthView", "pub fn health"):
    if token not in application:
        fail("application service contract missing " + token)

domain = read("src-tauri/src/domain/system.rs")
for token in ("ServiceIdentity", "RuntimeKind", "pub const fn desktop"):
    if token not in domain:
        fail("domain value contract missing " + token)

adapter = read("src-tauri/src/desktop_api.rs")
for token in (
    "tauri::State",
    "ApplicationServices",
    "health_to_wire",
    "app.system().health()",
    "#[tauri::command]",
):
    if token not in adapter:
        fail("Tauri adapter is not thin/application-backed: missing " + token)
for forbidden in ("env!(\"CARGO_PKG_VERSION\")", "PgPool", "sqlx", "reqwest", "axum"):
    if forbidden in adapter:
        fail("desktop adapter regained application/storage responsibility: " + forbidden)

main = read("src-tauri/src/main.rs")
for token in (
    "mod application;",
    "mod domain;",
    ".manage(application::ApplicationServices::desktop())",
    "generate_handler![",
    "desktop_api::desktop_api_health",
):
    if token not in main:
        fail("native composition root missing " + token)

# A03 protects the application/domain source boundary. Later adapter stages may
# add persistence crates to Cargo.toml without invalidating A03.

# Unit tests must exercise core behavior and the adapter mapping; UTS Cargo test is the compile gate.
for rel, test_name in (
    ("src-tauri/src/domain/system.rs", "desktop_identity_is_transport_agnostic"),
    ("src-tauri/src/application/system.rs", "health_read_model_is_stable_without_transport_runtime"),
    ("src-tauri/src/application/mod.rs", "desktop_registry_exposes_application_service_without_platform_adapter"),
    ("src-tauri/src/desktop_api.rs", "adapter_maps_application_read_model_to_existing_wire_contract"),
):
    if test_name not in read(rel):
        fail("missing Rust regression test " + test_name)

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("canonical UTS plan schema mismatch")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a03" not in ids or ids.index("a03") <= ids.index("a02d"):
    fail("A03 deterministic gate must follow A02d")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "| A03 Rust application/domain boundary" not in status or "**implemented** | A04" not in status:
    fail("implementation ledger does not mark A03 implemented with A04 next")
evidence = read("docs/evidence/A03_APPLICATION_DOMAIN_BOUNDARY.md")
for token in ("Fact", "Inference", "Proposal", "Unresolved experiment", "PgPool", "A04"):
    if token not in evidence:
        fail("A03 evidence/classification missing " + token)

print("A03 Rust application/domain boundary: OK")
