#!/usr/bin/env python3
"""Deterministic/network-free A02b UTS-build-fix + verifier contract gate."""
from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A02b CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


# The exact UTS failure was generate_context! trying to open this asset.
icon = ROOT / "src-tauri/icons/icon.png"
if not icon.is_file():
    fail("Tauri application icon missing")
raw = icon.read_bytes()
if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) < 33:
    fail("icon.png is not a valid PNG envelope")
if raw[12:16] != b"IHDR":
    fail("icon.png first chunk must be IHDR")
width, height, depth, color_type = struct.unpack(">IIBB", raw[16:26])
if width < 32 or height < 32 or depth != 8 or color_type != 6:
    fail(f"icon.png must be >=32x32 8-bit RGBA; got {width}x{height}, depth={depth}, color={color_type}")

conf = json.loads(read("src-tauri/tauri.conf.json"))
if conf.get("bundle", {}).get("icon") != ["icons/icon.png"]:
    fail("tauri.conf.json must explicitly own the icon path")

pkg = json.loads(read("package.json"))
lock = json.loads(read("package-lock.json"))
if pkg.get("engines", {}).get("node") != ">=20":
    fail("Node build-time floor should not retain the disproven <23 cap")
if lock.get("packages", {}).get("", {}).get("engines", {}).get("node") != ">=20":
    fail("package-lock root Node engine drift")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema mismatch")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for expected in ("a00", "a01", "a01b", "a01c", "a02", "a02b"):
    if expected not in ids:
        fail("UTS plan missing deterministic check " + expected)
if "--offline" not in plan.get("frontend", {}).get("offlineInstall", []):
    fail("frontend default preparation must be offline")
for key in ("lockOffline", "fetchOffline", "test", "build"):
    if "--offline" not in plan.get("cargo", {}).get(key, []):
        fail("Cargo acceptance command is not offline: " + key)

verifier = read("tools/uts_verify.py")
compile(verifier, "tools/uts_verify.py", "exec")
for required in ("--allow-network", ".uts-reports", "latest-summary.txt", "latest-results.json", "offline_then_optional_network"):
    if required not in verifier:
        fail("UTS verifier missing contract token: " + required)
# Check executable primitives, not prose/docstrings. The verifier may document
# that it does not use sudo/systemd/Docker without that becoming a false positive.
for forbidden in ("shell=True", "[\"sudo\"", "[\"pacman\"", "[\"systemctl\"", "[\"docker\""):
    if forbidden in verifier:
        fail("UTS verifier contains forbidden executable side-effect primitive: " + forbidden)

ignore = read(".gitignore")
if "/.uts-reports/" not in ignore:
    fail("UTS generated reports must be ignored")

canonical = read("docs/UTS_VERIFICATION.md")
if "python3 -B tools/uts_verify.py" not in canonical or "--allow-network" not in canonical:
    fail("canonical UTS documentation missing single-entry commands")
legacy = read("docs/UTS_A01_A02_VERIFICATION.md")
if "superseded" not in legacy.lower() or "UTS_VERIFICATION.md" not in legacy:
    fail("legacy UTS doc must not remain a competing SSOT")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A02b" not in status or "icon.png" not in status or "tools/uts_verify.py" not in status:
    fail("implementation ledger missing A02b correction")

print("A02b icon/build correction + unified UTS verifier contract: OK")
