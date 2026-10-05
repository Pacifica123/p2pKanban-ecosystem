#!/usr/bin/env python3
"""Deterministic/network-free A04 repository semantic contract gate."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A04 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


required = [
    "src-tauri/src/domain/planner.rs",
    "src-tauri/src/application/repository.rs",
    "src-tauri/src/application/repository/contract.rs",
    "evidence/a04-repository-semantics.json",
    "docs/evidence/A04_REPOSITORY_CONTRACTS.md",
]
for rel in required:
    read(rel)

# The contract must remain platform/storage independent.
core_files = [
    ROOT / "src-tauri/src/domain/planner.rs",
    ROOT / "src-tauri/src/application/repository.rs",
    ROOT / "src-tauri/src/application/repository/contract.rs",
]
forbidden = (
    "tauri::",
    "sqlx",
    "PgPool",
    "Postgres",
    "rusqlite",
    "sqlite",
    "postgres://",
    "postgresql://",
    "axum",
    "reqwest",
    "std::fs",
    "std::net",
    "std::process",
    "tokio::",
)
for path in core_files:
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    for token in forbidden:
        if token.lower() in lowered:
            fail(f"storage/platform token escaped into A04 core: {token} in {path.relative_to(ROOT)}")

planner = read("src-tauri/src/domain/planner.rs")
for token in (
    "struct AccessEpoch",
    "struct OrderKey",
    "struct VersionStamp",
    "struct CardRecord",
    "struct CardTombstone",
    "enum CardLifecycle",
    "compare_card_order",
    "logical_clock",
    "replica_id",
    "event_id",
):
    if token not in planner:
        fail("planner semantic value missing " + token)

repo = read("src-tauri/src/application/repository.rs")
for token in (
    "trait PlannerRepository",
    "struct PlannerTransaction",
    "enum PlannerMutation",
    "StaleAccessEpoch",
    "Tombstoned",
    "fn commit",
    "list_column_cards",
):
    if token not in repo:
        fail("repository contract missing " + token)

contract = read("src-tauri/src/application/repository/contract.rs")
for test_name in (
    "in_memory_reference_adapter_passes_repository_semantics",
    "stale_capability_epoch_rejects_the_entire_transaction",
    "failing_batch_rolls_back_earlier_mutations",
    "reorder_is_atomic_column_scoped_and_deterministic",
):
    if test_name not in contract:
        fail("repository scenario missing " + test_name)
for token in (
    "assert_repository_contract<R: PlannerRepository>",
    "RepositoryError::Tombstoned",
    "RepositoryError::StaleAccessEpoch",
    "DuplicateReorderItem",
):
    if token not in contract:
        fail("contract suite lost semantic assertion " + token)

# Helper functions used by the generic contract runner must stay adapter-agnostic.
if "fn create(repo: &mut InMemoryPlannerRepository" in contract:
    fail("contract helper create() is coupled to InMemoryPlannerRepository")
if not re.search(r"fn\s+create\s*<\s*R\s*:\s*PlannerRepository\s*>\s*\(\s*repo\s*:\s*&mut\s+R", contract):
    fail("contract helper create() must be generic over PlannerRepository")

# Evidence anchors/classification are part of the SSOT and must be hash-shaped.
evidence = json.loads(read("evidence/a04-repository-semantics.json"))
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A04":
    fail("A04 evidence format/stage mismatch")
sources = evidence.get("sources")
if not isinstance(sources, list) or len(sources) < 9:
    fail("A04 source archaeology inventory is incomplete")
for item in sources:
    digest = item.get("sha256")
    path = item.get("path")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("invalid A04 source digest")
    if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
        fail("unsafe A04 source path")
for key in ("facts", "inferences", "proposals", "unresolved"):
    values = evidence.get(key)
    if not isinstance(values, list) or not values:
        fail("A04 evidence classification missing " + key)
unresolved = "\n".join(evidence["unresolved"])
if "1024" not in unresolved or "1000" not in unresolved:
    fail("position allocation divergence must stay explicit")

# A04's invariant is that persistence never leaks into the domain/application
# contract files. Later stages may add adapter dependencies to Cargo.toml.

# Module wiring.
if "pub mod planner;" not in read("src-tauri/src/domain/mod.rs"):
    fail("domain planner module is not wired")
if "pub mod repository;" not in read("src-tauri/src/application/mod.rs"):
    fail("application repository module is not wired")

# Canonical UTS plan and older gates must remain forward compatible.
a03 = read("tools/check_a03.py")
if 'plan.get("stage") != "A03"' in a03:
    fail("A03 checker still freezes the UTS plan at A03")
plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("canonical UTS plan schema mismatch")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a04" not in ids or ids.index("a04") <= ids.index("a03"):
    fail("A04 deterministic gate must follow A03")

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((line for line in status.splitlines() if "A04 repository semantic contract suite" in line), "")
if "**implemented" not in line or "A05" not in line:
    fail("implementation ledger did not advance A04 to implemented/A05")
# A04 history is permanent in the implementation ledger; NEXT_PATCH_SEQUENCE is intentionally current-stage only.
if "| A05 " not in status:
    fail("implementation ledger lost the A05 architecture stage following A04")

doc = read("docs/evidence/A04_REPOSITORY_CONTRACTS.md")
for token in ("Fact", "Inference", "Proposal", "Unresolved", "1024", "1000", "A05"):
    if token not in doc:
        fail("A04 evidence document missing " + token)

print("A04 repository semantic contracts: OK")
