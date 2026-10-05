#!/usr/bin/env python3
"""Deterministic, offline A00 contract check.

This gate intentionally uses only the Python standard library. It validates the
permanent evidence/SSOT foundation without installing packages or contacting any
network service. Runtime/build checks begin in A01 because A00 adds no runtime
code.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from repository_contract import generated_tracked_paths, tracked_relative_paths

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "ARCH_NATIVE_REPO",
    "README.md",
    "docs/IMPLEMENTATION_STATUS.md",
    "docs/NEXT_PATCH_SEQUENCE.md",
    "docs/evidence/A00_EVIDENCE_BASELINE.md",
    "docs/architecture/README.md",
    "docs/architecture/00-executive-architecture.md",
    "docs/architecture/01-current-state-reconstruction.md",
    "docs/architecture/02-requirements-options-adr.md",
    "docs/architecture/03-components-data-storage-sync-security.md",
    "docs/architecture/04-arch-integration-packaging-update.md",
    "docs/architecture/05-release-diagnostics-performance-risk.md",
    "docs/architecture/06-compatibility-migration.md",
    "docs/architecture/07-roadmap-devctl-tests-experiments-do-not.md",
    "docs/architecture/08-implementation-corrections-and-debt.md",
    "docs/architecture/20-sources-and-evidence.md",
    "docs/architecture/adr/ADR-001-shell-and-process-model.md",
    "docs/architecture/adr/ADR-002-storage.md",
    "docs/architecture/adr/ADR-003-packaging-update-and-rollback.md",
    "docs/architecture/adr/ADR-004-secrets.md",
    "docs/architecture/adr/ADR-005-ipc-and-lan-bridge.md",
    "docs/architecture/adr/ADR-006-background-lifecycle.md",
    "docs/provenance/architecture-original-README.md",
    "docs/provenance/architecture-source-manifest.sha256",
    "evidence/source-anchors.json",
    "evidence/migrations.sha256",
    "fixtures/protocol/sync-envelope-v1.json",
    "fixtures/protocol/roaming-card-put-v1.json",
    "fixtures/protocol/roaming-card-delete-v1.json",
    "fixtures/protocol/device-link-grant-v2.json",
    "fixtures/export/portable-board-bundle-v1.json",
]

EXPECTED_ARCHIVE_HASHES = {
    "webBackend": "8b7346397b6135b4f2b7c27f59d32f522ea9eb5b34e3b22530606f1302ce9ce6",
    "android": "c463f8fd5a99c1a5214e2ed98044875ba74b78aa0023b0e011eefb205685de5d",
    "devctl": "c4876b3bd55f8fd996f248d9c18e78c961471e502c6ac578c1c124105c06c9af",
    "architecture": "0d93f7a7703c318def609861248b5a61f8998077080067ebad3431b149b5e906",
}

FORBIDDEN_FIXTURE_KEYS = {
    "accessToken",
    "refreshToken",
    "boardKey",
    "privateKey",
    "password",
    "sessionCookie",
    "deploymentSecret",
}

FORBIDDEN_REPO_PATHS = {
    ".devctl",
    "node_modules",
    "target",
    "dist",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "docker-compose.dev.yml",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(relative: str):
    path = ROOT / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {relative}: {exc}")


def walk_keys(value, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, key
            yield from walk_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, f"{path}[{index}]")


def check_required_files() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail("missing required A00 files: " + ", ".join(missing))
    if (ROOT / "ARCH_NATIVE_REPO").read_text(encoding="utf-8") != "p2pkanban-archlinux-native\n":
        fail("ARCH_NATIVE_REPO sentinel is invalid")


def check_architecture_classification() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "docs/architecture").rglob("*.md"))
    )
    for marker in ("[FACT]", "[INFERENCE]", "[PROPOSAL]", "[EXPERIMENT-NEEDED]"):
        if marker not in text:
            fail(f"architecture classification marker missing: {marker}")


def check_status_ledger() -> None:
    text = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    for number in range(20):
        stage = f"A{number:02d}"
        if stage not in text:
            fail(f"stage missing from implementation ledger: {stage}")
    a00_line = next((line for line in text.splitlines() if "A00 evidence baseline" in line), "")
    if "**implemented**" not in a00_line:
        fail("A00 evidence baseline must remain implemented as later stages advance")
    roadmap = (ROOT / "docs/architecture/07-roadmap-devctl-tests-experiments-do-not.md").read_text(encoding="utf-8")
    if "| A01 |" not in roadmap or "| A02 |" not in roadmap or roadmap.index("| A01 |") >= roadmap.index("| A02 |"):
        fail("architecture roadmap must preserve the A01 -> A02 ordering")
    debt = (ROOT / "docs/architecture/08-implementation-corrections-and-debt.md").read_text(encoding="utf-8")
    if "DEBT-A00-001" not in debt or "seed commit" not in debt or "git reset --hard HEAD" not in debt:
        fail("devctl commitless-repository rollback debt must stay explicit")


def check_source_anchors() -> None:
    data = load_json("evidence/source-anchors.json")
    if data.get("formatVersion") != 1:
        fail("source anchor formatVersion must be 1")
    snapshots = data.get("logicalSnapshots")
    if not isinstance(snapshots, dict):
        fail("logicalSnapshots missing")
    for name, expected in EXPECTED_ARCHIVE_HASHES.items():
        actual = ((snapshots.get(name) or {}).get("sha256"))
        if actual != expected:
            fail(f"snapshot hash drift for {name}: {actual!r}")
    anchors = data.get("anchors")
    if not isinstance(anchors, list) or len(anchors) < 25:
        fail("high-value source anchor inventory is unexpectedly small")
    for item in anchors:
        if not isinstance(item, dict):
            fail("source anchor entry must be an object")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail(f"invalid source anchor sha256: {item!r}")
        path = item.get("path")
        if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
            fail(f"unsafe source anchor path: {path!r}")


def check_migration_digest() -> None:
    lines = [line.strip() for line in (ROOT / "evidence/migrations.sha256").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 19:
        fail(f"expected 19 legacy migration digests, found {len(lines)}")
    for expected_number, line in enumerate(lines, start=1):
        match = re.fullmatch(r"([0-9a-f]{64})  (\d{4}_[^/]+\.sql)", line)
        if not match:
            fail(f"invalid migration digest line: {line}")
        if int(match.group(2)[:4]) != expected_number:
            fail(f"migration sequence is not contiguous at {match.group(2)}")


def check_fixtures() -> None:
    fixtures = {
        "sync": load_json("fixtures/protocol/sync-envelope-v1.json"),
        "roamingPut": load_json("fixtures/protocol/roaming-card-put-v1.json"),
        "roamingDelete": load_json("fixtures/protocol/roaming-card-delete-v1.json"),
        "deviceLink": load_json("fixtures/protocol/device-link-grant-v2.json"),
        "bundle": load_json("fixtures/export/portable-board-bundle-v1.json"),
    }
    if fixtures["sync"].get("protocolVersion") != "p2p-kanban-sync/1":
        fail("sync fixture protocol drift")
    if fixtures["roamingPut"].get("protocolVersion") != "p2p-kanban-roaming/1":
        fail("roaming put fixture protocol drift")
    deletion = fixtures["roamingDelete"]
    if deletion.get("operation") != "card.delete" or deletion.get("fieldMask") != ["__lifecycle"]:
        fail("roaming delete fixture must freeze global tombstone lifecycle semantics")
    if fixtures["deviceLink"].get("protocol") != "p2p-kanban-device-link/2":
        fail("device-link fixture protocol drift")
    manifest = fixtures["bundle"].get("manifest.json") or {}
    if manifest.get("format") != "p2p_planner_bundle" or manifest.get("formatVersion") != 1:
        fail("portable bundle fixture format drift")
    if manifest.get("includesLocalMetadata") is not False:
        fail("portable fixture must not leak device-local metadata")
    for name, value in fixtures.items():
        bad = sorted({key for _path, key in walk_keys(value) if key in FORBIDDEN_FIXTURE_KEYS})
        if bad:
            fail(f"secret-bearing keys are forbidden in A00 fixture {name}: {bad}")


def check_repo_hygiene() -> None:
    tracked = tracked_relative_paths(ROOT)
    tracked_set = set(tracked)
    for name in FORBIDDEN_REPO_PATHS:
        prefix = name.rstrip("/") + "/"
        if name in tracked_set or any(rel.startswith(prefix) for rel in tracked):
            fail(f"forbidden A00 runtime/generated path is tracked: {name}")
    generated = generated_tracked_paths(ROOT)
    if generated:
        fail("generated paths must not be tracked: " + ", ".join(generated[:10]))
    for rel in tracked:
        path = ROOT / rel
        parts = Path(rel).parts
        if any(part in {"__pycache__", ".pytest_cache"} for part in parts):
            fail(f"generated cache is tracked: {rel}")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo", ".sqlite", ".sqlite3", ".db"}:
            fail(f"generated/runtime artifact is tracked: {rel}")
        if path.is_symlink():
            fail(f"symlinks are not part of the repository contract: {rel}")


def check_internal_manifest_hash_format() -> None:
    path = ROOT / "docs/provenance/architecture-source-manifest.sha256"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if not re.match(r"^[0-9a-f]{64}\s{2,}", line):
            fail(f"invalid copied architecture manifest line: {line}")


def main() -> int:
    checks = [
        check_required_files,
        check_architecture_classification,
        check_status_ledger,
        check_source_anchors,
        check_migration_digest,
        check_fixtures,
        check_repo_hygiene,
        check_internal_manifest_hash_format,
    ]
    for check in checks:
        check()
        print(f"[ok] {check.__name__}")
    print("A00 evidence/SSOT baseline is deterministic and internally consistent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
