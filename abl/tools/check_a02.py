#!/usr/bin/env python3
"""Deterministic/network-free A02 transport-boundary gate."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def fail(msg: str) -> None:
    raise SystemExit("A02 CHECK FAILED: " + msg)

def read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file(): fail("missing " + rel)
    return p.read_text(encoding="utf-8")

pkg = json.loads(read("package.json"))
lock = json.loads(read("package-lock.json"))
if pkg.get("dependencies", {}).get("@tauri-apps/api") != "2.11.1": fail("@tauri-apps/api must be exact 2.11.1")
entry = lock.get("packages", {}).get("node_modules/@tauri-apps/api", {})
if entry.get("version") != "2.11.1": fail("npm lock missing exact Tauri API package")
if entry.get("integrity") != "sha512-M2FPuYND2m+wh5hfW9ZpSdxMPdEJovPBWwoHJmwUpysTYNHaOkVFN419m/K0LIgjb/7KU2vBgsUepJWugQCvAA==": fail("Tauri API lock integrity drift")

desktop = read("src/shared/transport/desktop.ts")
for token in ("@tauri-apps/api/core", "desktop_api_health", "path === '/health'", "DESKTOP_ROUTE_UNSUPPORTED"):
    if token not in desktop: fail("desktop adapter missing " + token)
for forbidden in ("fetch(", "http://", "https://", "window.__TAURI", "__TAURI_INTERNALS__", "plugin-fs", "plugin-shell", "plugin-http"):
    if forbidden in desktop: fail("desktop adapter contains forbidden direct capability: " + forbidden)

# Tauri JS API access is centralized in exactly one file.
for p in (ROOT / "src").rglob("*.ts*"):
    text = p.read_text(encoding="utf-8")
    if "@tauri-apps/api" in text and p.relative_to(ROOT).as_posix() != "src/shared/transport/desktop.ts":
        fail("Tauri JS API escaped transport boundary: " + p.relative_to(ROOT).as_posix())

web = read("src/shared/transport/web.ts")
if "fetchImpl" not in web or "credentials: 'include'" not in web: fail("web HTTP adapter contract missing")
client = read("src/shared/api/client.ts")
if "activeTransport" not in client or "desktopTransport" not in client or "apiRequest" not in client: fail("apiRequest facade missing")
version = read("src/features/system/api/version.ts")
if "apiRequest<BackendVersion>('/health')" not in version: fail("web-compatible health caller shape drifted")

rust = read("src-tauri/src/desktop_api.rs")
main = read("src-tauri/src/main.rs")
if "#[tauri::command]" not in rust or "desktop_api_health" not in rust: fail("Rust command missing")
if "generate_handler![" not in main or "desktop_api::desktop_api_health" not in main: fail("Rust health command is not explicitly allowlisted")
for forbidden in ("TcpListener", "std::process::Command", "std::fs", "reqwest", "axum", "sqlx"):
    if forbidden in rust: fail("A02 probe command gained forbidden capability: " + forbidden)

cap = json.loads(read("src-tauri/capabilities/main-minimal.json"))
if cap.get("permissions") not in ([], None): fail("A02 must not add broad Tauri capability permissions")

runtime_files = [
    ROOT / "src/shared/api/client.ts",
    ROOT / "src/shared/transport/desktop.ts",
    ROOT / "src/shared/transport/web.ts",
    ROOT / "src-tauri/src/desktop_api.rs",
    ROOT / "src-tauri/src/main.rs",
]
all_src = "\n".join(p.read_text(encoding="utf-8") for p in runtime_files)
for forbidden in ("http://localhost", "https://localhost", "http://127.0.0.1", "https://127.0.0.1", "postgres://", "postgresql://"):
    if forbidden in all_src.lower(): fail("forbidden runtime assumption in A02 source: " + forbidden)

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A02" not in status or "A03" not in status: fail("implementation ledger missing A02/A03")
evidence = read("docs/evidence/A02_TRANSPORT_BOUNDARY.md")
if "UTS_VERIFICATION.md" not in evidence or "A02B_UTS_BUILD_FINDINGS.md" not in evidence: fail("A02 evidence must point to canonical UTS gate/findings")
print("A02 typed transport boundary: OK")
