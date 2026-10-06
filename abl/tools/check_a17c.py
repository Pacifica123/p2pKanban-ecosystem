#!/usr/bin/env python3
"""CORR-A17-001: the whole Tauri crate family stays on the 2.11 line together.

`tauri =2.11.5` alone let fresh lock re-resolution pick tauri-runtime 2.12.x and
tauri-macros/codegen 2.7.x, which do not compile against tauri 2.11.5. Every
family member that tauri 2.11.5 depends on with a caret requirement is pinned.
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAMILY = {
    "tauri": "2.11.5",
    "tauri-runtime": "2.11.3",
    "tauri-runtime-wry": "2.11.4",
    "tauri-macros": "2.6.3",
    "tauri-codegen": "2.6.3",
    "tauri-utils": "2.9.3",
}


def fail(message: str) -> None:
    raise SystemExit("A17c CHECK FAILED: " + message)


manifest = tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
lock = tomllib.loads((ROOT / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
deps = manifest.get("dependencies", {})
for name, version in FAMILY.items():
    spec = deps.get(name)
    pin = spec if isinstance(spec, str) else (spec or {}).get("version")
    if pin != "=" + version:
        fail(f"{name} must be exact-pinned to ={version}, found {pin!r}")
    locked = sorted({p["version"] for p in lock["package"] if p["name"] == name})
    if locked != [version]:
        fail(f"Cargo.lock must carry only {name} {version}, found {locked}")
build = manifest.get("build-dependencies", {}).get("tauri-build")
if (build if isinstance(build, str) else (build or {}).get("version")) != "=2.6.3":
    fail("tauri-build must stay =2.6.3 with the 2.11 family")
doc = (ROOT / "docs/architecture/08-implementation-corrections-and-debt.md").read_text(encoding="utf-8")
if "CORR-A17-001" not in doc:
    fail("CORR-A17-001 must be recorded in 08-implementation-corrections-and-debt.md")
print("A17c OK: Tauri family pinned to the 2.11 line in Cargo.toml and Cargo.lock")
