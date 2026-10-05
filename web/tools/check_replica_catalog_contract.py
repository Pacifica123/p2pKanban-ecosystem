#!/usr/bin/env python3
"""Static gate for the asynchronous board-catalog recovery path."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def require(path: str, fragments: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise SystemExit(f"{path}: missing replica recovery contracts: {missing}")

require("backend/crates/nostr-transport/src/lib.rs", [
    "DEVICE_CATALOG_PROTOCOL",
    "publish_device_catalog",
    "recover_device_catalogs",
    "device_link::decrypt",
])
require("backend/src/transports/roaming.rs", [
    "ingest_device_catalogs",
    "apply_device_catalog",
    "publish_device_catalogs",
    "apply_remote_board_snapshot",
    "Remember the delegated peer discovered through a signed relay event.",
])
require("backend/migrations/0021_device_catalog_recovery.sql", [
    "roaming_device_catalog_receipts",
    "payload_json jsonb not null",
    "primary key(device_public_key,board_id)",
])
print("replica catalog recovery contract: OK")
