#!/usr/bin/env python3
"""Проверяет статический контракт связывания двух web-узлов v1."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(relative: str, *needles: str) -> None:
    content = read(relative)
    missing = [needle for needle in needles if needle not in content]
    if missing:
        raise SystemExit(f"FAIL: {relative} is missing: {', '.join(missing)}")


def main() -> None:
    version = read("VERSION").strip()
    frontend = json.loads(read("frontend/package.json"))
    backend_manifest = tomllib.loads(read("backend/Cargo.toml"))
    if frontend.get("version") != version or backend_manifest["package"]["version"] != version:
        raise SystemExit("FAIL: current frontend/backend/VERSION are not aligned")

    cargo_lock = tomllib.loads(read("backend/Cargo.lock"))
    backend_package = next(
        package
        for package in cargo_lock["package"]
        if package["name"] == "p2p-planner-backend"
    )
    if "reqwest" not in backend_package.get("dependencies", []):
        raise SystemExit("FAIL: backend Cargo.lock does not include direct reqwest dependency")

    require(
        "backend/migrations/0013_web_node_link_identity.sql",
        "local_node_identity",
        "roaming_board_capabilities",
        "board_key_base64",
    )
    require(
        "backend/src/auth/pairing.rs",
        "export_node_link",
        "import_node_link",
        "ensure_empty_destination",
        "jsonb_to_recordset",
        "source_export_endpoint",
    )
    require(
        "backend/src/transports/roaming.rs",
        "local_node_identity",
        "publish_roaming_with_board_key",
        "recover_roaming_with_board_key",
    )
    require(
        "frontend/src/features/auth/pages/AuthPage.tsx",
        "Подключить с другого узла",
        "Подключить и перенести доски",
        "Совпадающий email на другом узле не связывает аккаунты",
    )
    require(
        "docs/api/openapi.yaml",
        "/auth/node-link/export:",
        "/auth/node-link/import:",
        "NodeLinkImportRequest:",
    )
    require(
        "docs/product/github-devctl-project-integration-concept-v1.md",
        "SourceConnector",
        "NormalizedExternalEvent",
        "observe(checkpoint)",
        "подписанный webhook",
    )
    print("OK: web-node identity transfer, imported board capabilities and ER ingress are aligned")


if __name__ == "__main__":
    main()
