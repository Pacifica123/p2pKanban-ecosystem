#!/usr/bin/env python3
"""Offline deterministic A01 source/security contract check."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from repository_contract import generated_tracked_paths, tracked_files, tracked_relative_paths

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"A01 CHECK FAILED: {message}")


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail(f"missing required file: {rel}")
    return path.read_text(encoding="utf-8")


def load_json(rel: str) -> dict:
    try:
        return json.loads(read(rel))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {rel}: {exc}")


required = [
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.mjs",
    "index.html",
    "src/main.tsx",
    "src/App.tsx",
    "src/styles.css",
    "src-tauri/Cargo.toml",
    "src-tauri/build.rs",
    "src-tauri/src/main.rs",
    "src-tauri/src/navigation_policy.rs",
    "src-tauri/tauri.conf.json",
    "src-tauri/capabilities/main-minimal.json",
    "docs/evidence/A01_SHELL_FOUNDATION.md",
]
for rel in required:
    if not (ROOT / rel).is_file():
        fail(f"missing required file: {rel}")

# Frontend dependency contract: exact pins, no Tauri JS bridge or web networking package in A01a.
pkg = load_json("package.json")
expected_deps = {"react": "18.3.1", "react-dom": "18.3.1"}
expected_dev = {
    "@types/react": "18.3.28",
    "@types/react-dom": "18.3.7",
    "@vitejs/plugin-react": "4.7.0",
    "typescript": "5.9.3",
    "vite": "5.4.21",
}
deps = pkg.get("dependencies", {})
for name, version in expected_deps.items():
    if deps.get(name) != version:
        fail(f"A01 base dependency drift: {name}@{version}")
allowed_later = {"@tauri-apps/api"}
if set(deps) - set(expected_deps) - allowed_later:
    fail("unexpected runtime dependency outside reviewed staged set")
if pkg.get("devDependencies") != expected_dev:
    fail("package.json devDependencies differ from the reviewed A01a set")
if pkg.get("scripts", {}).get("build") != "tsc --noEmit && vite build":
    fail("frontend build must typecheck before Vite build")
# A02 may add the official Tauri core JS transport package; A01 still forbids privilege plugins.

# package-lock must exactly describe the root pins and carry immutable registry integrity metadata.
lock = load_json("package-lock.json")
if lock.get("lockfileVersion") != 3:
    fail("package-lock.json must use lockfileVersion 3")
root_lock = lock.get("packages", {}).get("")
if not isinstance(root_lock, dict):
    fail("package-lock.json missing root package entry")
root_deps = root_lock.get("dependencies", {})
for name, version in expected_deps.items():
    if root_deps.get(name) != version:
        fail(f"package-lock lost A01 base dependency: {name}@{version}")
if root_lock.get("devDependencies") != expected_dev:
    fail("package-lock A01 devDependency set drifted")
for name, version in {**expected_deps, **expected_dev}.items():
    entry = lock["packages"].get(f"node_modules/{name}")
    if not isinstance(entry, dict) or entry.get("version") != version:
        fail(f"locked package mismatch for {name}@{version}")
    if not entry.get("integrity"):
        fail(f"locked package lacks integrity metadata: {name}")

# Tauri config: packaged assets only, no localhost dev URL, no configured JS privileges.
config = load_json("src-tauri/tauri.conf.json")
build = config.get("build", {})
if build.get("frontendDist") != "../dist":
    fail("Tauri frontendDist must point to packaged Vite output")
for forbidden_key in ("devUrl", "beforeDevCommand"):
    if forbidden_key in build:
        fail(f"A01a must not require a development server: build.{forbidden_key}")
app = config.get("app", {})
if app.get("windows") != []:
    fail("window must be constructed in Rust so navigation hooks cannot be bypassed by config")
security = app.get("security", {})
csp = security.get("csp", "")
for directive in ("default-src 'self'", "connect-src 'none'", "object-src 'none'", "frame-src 'none'", "form-action 'none'"):
    if directive not in csp:
        fail(f"CSP missing required directive: {directive}")
if security.get("capabilities") != ["main-minimal"]:
    fail("only the reviewed main-minimal capability may be enabled")

capability = load_json("src-tauri/capabilities/main-minimal.json")
if capability.get("windows") != ["main"] or capability.get("permissions") != []:
    fail("A01a WebView capability must grant zero Tauri commands")
if capability.get("remote") is not None:
    fail("remote origins must not receive capabilities")

# Native shell policy: Rust owns window creation and denies remote navigation/new windows/downloads.
main_rs = read("src-tauri/src/main.rs")
nav_rs = read("src-tauri/src/navigation_policy.rs")
required_rust_tokens = [
    "WebviewWindowBuilder::new",
    "WebviewUrl::App",
    ".on_navigation(navigation_policy::allows_top_level_navigation)",
    ".on_new_window(|_, _| NewWindowResponse::Deny)",
    ".on_download(|_, _| false)",
    ".devtools(false)",
]
for token in required_rust_tokens:
    if token not in main_rs:
        fail(f"Rust shell missing security boundary: {token}")
if 'url.scheme() == "tauri"' not in nav_rs:
    fail("navigation allowlist must accept only Tauri packaged origin")
for hostile in (
    "https://example.com/",
    "http://localhost:5173/",
    "http://127.0.0.1:3000/",
    "file:///tmp/index.html",
    "data:text/html,hello",
    "javascript:alert(1)",
):
    if hostile not in nav_rs:
        fail(f"navigation regression vector missing: {hostile}")

cargo = read("src-tauri/Cargo.toml")
try:
    cargo_doc = tomllib.loads(cargo)
except tomllib.TOMLDecodeError as exc:
    fail(f"invalid src-tauri/Cargo.toml: {exc}")
if cargo_doc.get("package", {}).get("rust-version") != "1.90":
    fail("Rust floor must stay explicit and aligned with Tauri 2.11.5 upstream MSRV")
if cargo_doc.get("dependencies", {}).get("tauri", {}).get("version") != "=2.11.5":
    fail("tauri dependency must be exactly pinned to 2.11.5")
if cargo_doc.get("build-dependencies", {}).get("tauri-build", {}).get("version") != "=2.6.3":
    fail("tauri-build dependency must be exactly pinned to 2.6.3")
for forbidden in ("axum", "sqlx", "postgres", "reqwest", "tokio", "hyper"):
    if forbidden in cargo_doc.get("dependencies", {}) or forbidden in cargo_doc.get("build-dependencies", {}):
        fail(f"forbidden A01a Rust dependency present: {forbidden}")

# Frontend must not itself create a network/storage authority or invoke privileged APIs.
frontend_text = "\n".join(read(rel) for rel in ("index.html", "src/main.tsx", "src/App.tsx", "src/styles.css", "vite.config.mjs"))
for forbidden in (
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "localStorage",
    "sessionStorage",
    "@tauri-apps/api",
    "http://localhost",
    "127.0.0.1",
):
    if forbidden in frontend_text:
        fail(f"frontend contains forbidden A01a runtime primitive: {forbidden}")
if re.search(r'''(?:src|href)=["']https?://''', frontend_text, re.I):
    fail("frontend references a remote runtime asset")

# A01a must not accidentally add the runtime technologies the native trajectory removes.
# Read only Git-tracked source files: UTS deliberately leaves ignored target/dist caches.
text_suffixes = {".rs", ".toml", ".json", ".ts", ".tsx", ".css", ".html", ".mjs"}
runtime_text = "\n".join(
    path.read_text(encoding="utf-8", errors="replace")
    for path in tracked_files(ROOT, "src", "src-tauri")
    if path.suffix.lower() in text_suffixes
)
for forbidden in ("docker-compose", "postgresql://", "postgres://", "systemctl --user", "sudo pacman"):
    if forbidden.lower() in runtime_text.lower():
        fail(f"runtime source contains forbidden dependency/assumption: {forbidden}")

# Hygiene means "not repository-owned", not "must not exist after a build".
# Ignored UTS caches are allowed to remain so repeated verification stays incremental.
generated = generated_tracked_paths(ROOT)
if generated:
    fail("generated directories/files must not be tracked: " + ", ".join(generated[:10]))
secret_suffixes = (".sqlite", ".sqlite3", ".db", ".db-wal", ".db-shm", ".pem", ".p12", ".pfx")
for rel in tracked_relative_paths(ROOT):
    if rel.lower().endswith(secret_suffixes):
        fail(f"runtime/secret artifact must not be tracked: {rel}")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "| A01 Tauri 2 shell + packaged React/Vite asset |" not in status:
    fail("implementation ledger lost A01 traceability")
if "**partially implemented" not in status and "**implemented**" not in status:
    fail("implementation ledger must state an explicit A01 implementation status")

print("A01 source/security contract: OK")
print("NOTE: source/security regression gate does not itself claim compile/launch evidence")
