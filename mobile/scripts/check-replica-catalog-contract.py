#!/usr/bin/env python3
"""Static gate for local-first board discovery without private-node HTTP."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def require(path: str, fragments: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise SystemExit(f"{path}: missing replica recovery contracts: {missing}")

require("src/features/boards/BoardsScreen.tsx", [
    "listLocalReplicaBoards",
    "refreshDeviceCatalog",
    "preferReplicaCatalog",
])
require("src/features/roaming/catalog.ts", [
    "DEVICE_CATALOG_PROTOCOL",
    "trustedPublishers",
    "installRoamingCapability",
])
require("src/features/roaming/storage.ts", [
    "CATALOG_CHANNEL_KEY",
    "SecureStore.setItemAsync(CATALOG_CHANNEL_KEY",
])
require("src/features/deviceLink/service.ts", [
    "listRoamingCapabilities",
    "capability.delegationChain",
    "overlayBoard",
])
print("Android replica catalog recovery contract: OK")
