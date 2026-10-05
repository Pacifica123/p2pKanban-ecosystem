#!/usr/bin/env python3
"""Deterministic/network-free A04b UTS compile-correction gate."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A04B CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")

contract = read("src-tauri/src/application/repository/contract.rs")
repo = read("src-tauri/src/application/repository.rs")

# Regression from real Manjaro UTS cargo.test: the reusable runner was generic,
# but create() accepted only the reference in-memory adapter.
if "fn create(repo: &mut InMemoryPlannerRepository" in contract:
    fail("compile regression remains: create() accepts only InMemoryPlannerRepository")
if not re.search(
    r"fn\s+create\s*<\s*R\s*:\s*PlannerRepository\s*>\s*\(\s*repo\s*:\s*&mut\s+R",
    contract,
):
    fail("create() is not generic over PlannerRepository")
if "assert_repository_contract<R: PlannerRepository>" not in contract:
    fail("generic repository contract runner missing")

# The compile warning exposed by the same UTS run should not survive the fix.
first_use = repo.split(";", 1)[0]
if "CardLifecycle" in first_use:
    fail("unused CardLifecycle import remains in application/repository.rs")

# Keep persistence out of the hotfix.
for rel in (
    "src-tauri/src/application/repository.rs",
    "src-tauri/src/application/repository/contract.rs",
):
    lowered = read(rel).lower()
    for token in ("sqlx", "postgres", "rusqlite", "sqlite", "diesel", "sea-orm"):
        if token in lowered:
            fail(f"A04b smuggled persistence token {token} into {rel}")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema mismatch")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required in ("a04", "a04b"):
    if required not in ids:
        fail("missing deterministic gate " + required)
if ids.index("a04b") <= ids.index("a04"):
    fail("A04b deterministic gate must follow A04")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A04b UTS compile correction" not in status:
    fail("implementation ledger does not record A04b")
evidence = read("docs/evidence/A04B_UTS_COMPILE_FIX.md")
for token in ("Fact", "Correction", "cargo test", "A05"):
    if token not in evidence:
        fail("A04b evidence document missing " + token)

print("A04b UTS compile correction: OK")
