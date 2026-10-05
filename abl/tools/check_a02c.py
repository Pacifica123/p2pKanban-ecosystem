#!/usr/bin/env python3
"""Deterministic/network-free A02c repeatable-UTS contract gate."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A02c CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")

helper = read("tools/repository_contract.py")
for token in ("git", "ls-files", "generated_tracked_paths", "tracked_files", ".uts-reports/"):
    if token not in helper:
        fail("repository-view helper missing contract token: " + token)
if "git clean" in helper or "shutil.rmtree" in helper:
    fail("repository-view helper must not delete UTS caches")

a00 = read("tools/check_a00.py")
if "tracked_relative_paths" not in a00 or "generated_tracked_paths" not in a00:
    fail("A00 hygiene must validate tracked repository content")
if 'if (ROOT / name).exists()' in a00:
    fail("A00 must not fail merely because ignored build output exists")

a01 = read("tools/check_a01.py")
for token in ("tracked_files", "tracked_relative_paths", "generated_tracked_paths"):
    if token not in a01:
        fail("A01 source/hygiene check missing tracked-file primitive: " + token)
if 'for base in runtime_paths' in a01 or 'if (ROOT / rel).exists()' in a01:
    fail("A01 retains working-tree/generated-directory scan")

a01b = read("tools/check_a01b.py")
if "version not in {3, 4}" not in a01b:
    fail("A01b must accept supported resolver-generated Cargo lock formats 3/4")

verifier = read("tools/uts_verify.py")
compile(verifier, "tools/uts_verify.py", "exec")
for token in ("run_deterministic_phase", '"postbuild.deterministic."', "No caches are deleted"):
    if token not in verifier:
        fail("UTS verifier missing repeatability contract: " + token)
for forbidden in ("git clean", "shutil.rmtree", "rm -rf"):
    if forbidden in verifier:
        fail("UTS verifier must preserve useful build caches: " + forbidden)

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema mismatch")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a02c" not in ids:
    fail("canonical UTS plan lost the A02c regression gate")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A02c" not in status or "repeat" not in status.lower():
    fail("implementation ledger missing A02c repeatability correction")
evidence = read("docs/evidence/A02C_UTS_REPEATABILITY_FINDINGS.md")
for token in ("overall: PASS", "exited `-9`", "Git-tracked", "Cargo lock formats 3 and 4"):
    if token not in evidence:
        fail("A02c evidence missing UTS finding: " + token)

print("A02c repeatable UTS/repository-view contract: OK")
