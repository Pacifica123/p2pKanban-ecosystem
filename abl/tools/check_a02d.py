#!/usr/bin/env python3
"""Deterministic/network-free A02d UTS snapshot-without-Git regression gate."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A02d CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


helper_path = ROOT / "tools/repository_contract.py"
spec = importlib.util.spec_from_file_location("repository_contract_a02d", helper_path)
if spec is None or spec.loader is None:
    fail("cannot import repository_contract.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

# Reproduce the real devctl UserTestSpace shape: no .git metadata, source files
# plus generated frontend/Cargo/report trees. Generated output must not enter the
# repository-owned view, while suspicious secret/runtime payload must remain
# visible so older hygiene checks can reject it.
with tempfile.TemporaryDirectory(prefix="p2pkanban-a02d-") as tmp:
    root = Path(tmp)
    (root / "src").mkdir()
    (root / "src/app.ts").write_text("export {}\n", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist/index.html").write_text("generated\n", encoding="utf-8")
    (root / "node_modules/pkg").mkdir(parents=True)
    (root / "node_modules/pkg/index.js").write_text("generated\n", encoding="utf-8")
    (root / "src-tauri/target/debug").mkdir(parents=True)
    (root / "src-tauri/target/debug/app").write_text("generated\n", encoding="utf-8")
    (root / ".uts-reports/x/logs").mkdir(parents=True)
    (root / ".uts-reports/x/logs/a.log").write_text("generated\n", encoding="utf-8")
    (root / ".env").write_text("SECRET_CANARY=must-remain-visible\n", encoding="utf-8")
    (root / "profile.sqlite").write_bytes(b"not-a-real-db")

    if helper.repository_view_mode(root) != "snapshot":
        fail("non-Git UTS-shaped directory was not recognized as snapshot mode")
    paths = helper.tracked_relative_paths(root)
    expected_visible = {"src/app.ts", ".env", "profile.sqlite"}
    if not expected_visible.issubset(set(paths)):
        fail("snapshot mode hid repository/security-relevant files")
    forbidden_generated = ("dist/", "node_modules/", "src-tauri/target/", ".uts-reports/")
    leaked = [rel for rel in paths if rel.startswith(forbidden_generated)]
    if leaked:
        fail("snapshot repository view leaked generated paths: " + ", ".join(leaked[:5]))
    if helper.generated_tracked_paths(root):
        fail("snapshot mode must not claim generated UTS output is Git-tracked")

# Older gates must remain forward-compatible as the canonical plan advances.
a02c = read("tools/check_a02c.py")
if 'plan.get("stage") != "A02c"' in a02c or 'ids[-1:] != ["a02c"]' in a02c:
    fail("A02c regression checker still freezes the canonical plan at A02c")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema mismatch")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a02d" not in ids:
    fail("canonical UTS plan missing A02d regression gate")
if ids.index("a02d") <= ids.index("a02c"):
    fail("A02d gate must follow A02c")

uts_doc = read("docs/UTS_VERIFICATION.md")
for token in ("does not contain `.git`", "global npm/Cargo caches", "fresh project-local"):
    if token not in uts_doc:
        fail("UTS SSOT missing snapshot/cache clarification: " + token)

evidence = read("docs/evidence/A02D_UTS_SNAPSHOT_FINDINGS.md")
for token in ("fatal: не найден git репозиторий", "UserTestSpace snapshot", "Git metadata", "global package caches"):
    if token not in evidence:
        fail("A02d evidence missing supplied UTS finding: " + token)

print("A02d Git-less UTS snapshot repository-view contract: OK")
