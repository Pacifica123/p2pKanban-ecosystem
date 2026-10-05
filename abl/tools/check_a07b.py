#!/usr/bin/env python3
"""Deterministic/network-free A07b UTS compile/build correction gate."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A07B CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


api_types = read("src/shared/api/types.ts")
app = read("src/App.tsx")
migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")

# UTS 20260912T155832Z: VaultStatus.durable was narrowed to the literal "false"
# while App intentionally renders the future-capability branch for "true" as well.
if "durable: 'true' | 'false';" not in api_types:
    fail("VaultStatus.durable must represent both wire values instead of the literal-only false type")
if "vault.durable === 'true'" not in app:
    fail("vault capability rendering no longer consumes the typed string wire contract")
if "durable: 'false';" in api_types:
    fail("A07 literal-only durable type regression returned")

# UTS 20260912T155832Z: Rust format! parsed the journal's opening JSON brace as
# a formatting placeholder. Literal braces must stay escaped in the source.
if '"{{\\n  \\"formatVersion\\": 1,' not in migration:
    fail("migration journal format string does not escape the opening literal JSON brace")
if '\\n}}\\n"' not in migration:
    fail("migration journal format string does not escape the closing literal JSON brace")
if '"{\\n  \\"formatVersion\\": 1,' in migration:
    fail("unescaped migration-journal opening brace regression returned")

# frontendDist failure in that UTS run was downstream of the failed frontend
# build. Keep packaged-asset ordering explicit in the canonical verifier plan.
plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("unsupported canonical UTS plan schema")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required in ("a07", "a07b"):
    if required not in ids:
        fail("missing deterministic gate " + required)
if ids.index("a07") >= ids.index("a07b"):
    fail("A07b deterministic gate must follow A07")
frontend = plan.get("frontend", {})
if frontend.get("requiredArtifact") != "dist/index.html":
    fail("packaged frontend artifact gate drifted")
if not frontend.get("build"):
    fail("frontend build must remain before Cargo acceptance")

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((line for line in status.splitlines() if "A07b UTS compile/build correction" in line), "")
if "implemented" not in line.lower() or "A08" not in line:
    fail("implementation ledger did not record A07b and preserve A08 as next stage")
# A07b history is permanent in status/evidence; current NEXT_PATCH_SEQUENCE must be free to advance.
if "| A08 " not in status:
    fail("implementation ledger lost the A08 architecture stage following A07b")
evidence = read("docs/evidence/A07B_UTS_BUILD_FIX.md")
for token in ("TS2367", "invalid format string", "frontendDist", "A08"):
    if token not in evidence:
        fail("A07b evidence note missing " + token)

print("A07b frontend/Rust compile correction: OK")
