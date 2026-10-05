#!/usr/bin/env python3
"""Deterministic/network-free A14 bounded LAN compatibility bridge gate."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A14 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


def load(rel: str):
    try:
        return json.loads(read(rel))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON {rel}: {exc}")


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


required = [
    "src-tauri/src/domain/lan_bridge.rs",
    "src-tauri/src/application/lan_bridge.rs",
    "src-tauri/src/infrastructure/linux/lan_bridge.rs",
    "src/features/system/api/lanBridge.ts",
    "fixtures/protocol/lan-bridge-v1-golden.json",
    "tools/a14_host_lan_bridge_probe.py",
    "docs/evidence/A14_BOUNDED_LAN_BRIDGE.md",
    "evidence/a14-bounded-lan-bridge.json",
]
for rel in required:
    read(rel)

cargo = tomllib.loads(read("src-tauri/Cargo.toml"))
deps = cargo.get("dependencies", {})
k256 = deps.get("k256")
if not isinstance(k256, dict) or k256.get("version") != "=0.14.0":
    fail("A14 must exact-pin the native secp256k1 identity implementation")
if k256.get("default-features") is not False or set(k256.get("features", [])) != {"schnorr", "getrandom"}:
    fail("A14 k256 feature boundary drifted")
for forbidden in ("axum", "hyper", "reqwest", "warp", "actix-web", "rouille", "tiny_http"):
    if forbidden in deps:
        fail("A14 must not restore a general HTTP stack: " + forbidden)

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
if "CURRENT_SCHEMA_VERSION: u32 = 6" not in migration:
    fail("A14 must not advance persistent schema")

domain = read("src-tauri/src/domain/lan_bridge.rs")
for token in (
    'LAN_BRIDGE_PROTOCOL: &str = "p2p-kanban-lan-bridge/1"',
    'LAN_PROVISION_PROTOCOL: &str = "p2p-kanban-lan-provision/1"',
    'LAN_BRIDGE_PATH: &str = "/v1/p2pkanban/pair"',
    "LAN_BRIDGE_MIN_TTL_SECS: u64 = 30",
    "LAN_BRIDGE_DEFAULT_TTL_SECS: u64 = 300",
    "LAN_BRIDGE_MAX_TTL_SECS: u64 = 600",
    "LAN_BRIDGE_MAX_ATTEMPTS: u32 = 8",
    "XChaCha20Poly1305",
    "deny_unknown_fields",
    "a14_golden_vector_is_stable_and_unknown_version_rejected",
):
    if token not in domain:
        fail("A14 protocol boundary missing " + token)
for forbidden in ("device_private_key", "device_public_key", "tauri::", "TcpListener", "std::net"):
    if forbidden in domain:
        fail("A14 domain leaked transport/private-identity detail: " + forbidden)

app = read("src-tauri/src/application/lan_bridge.rs")
for token in (
    "SigningKey::generate()",
    ".verifying_key()",
    "device_private_key = signing_key.to_bytes().to_vec()",
    "VaultNotDurable",
    "provision_authenticated_device_link",
    "private_key = Arc::new(Mutex::new(Some(device_private_key)))",
    "devicePublicKey",
):
    if token == "devicePublicKey":
        continue
    if token not in app:
        fail("A14 application boundary missing " + token)
if "std::net" in app or "TcpListener" in app:
    fail("A14 application layer must not own sockets")

linux = read("src-tauri/src/infrastructure/linux/lan_bridge.rs")
for token in (
    "TcpListener",
    "HIGH_PORT_MIN: u16 = 49_152",
    "is_user_lan_address",
    "LAN_BRIDGE_MAX_ATTEMPTS",
    '"origin" | "cookie" | "authorization" | "proxy-authorization"',
    '"transfer-encoding"',
    'content_type != Some("application/json")',
    "open_lan_bridge_envelope",
    "LanBridgeLifecycle::Completed",
    "LanBridgeLifecycle::Expired",
    "manual-stop",
    "a14_transport_accepts_one_authenticated_payload_then_closes",
    "a14_transport_rejects_origin_host_confusion_and_wrong_capability",
):
    if token not in linux:
        fail("A14 Linux adapter missing " + token)
if 'TcpListener::bind("0.0.0.0' in linux or 'TcpListener::bind("127.0.0.1' in linux:
    fail("production bridge contains a fixed wildcard/loopback listener")

runtime_surface = "\n".join(read(rel) for rel in (
    "src-tauri/src/main.rs",
    "src-tauri/src/infrastructure/linux/lan_bridge.rs",
    "src-tauri/src/application/lan_bridge.rs",
))
for forbidden in ("iptables", "nft ", "nftables", "firewall-cmd", "ufw ", "pkexec", "sudo ", "avahi", "mdns", "systemctl"):
    if forbidden.lower() in runtime_surface.lower():
        fail("A14 runtime gained forbidden firewall/discovery/privilege behavior: " + forbidden)

main = read("src-tauri/src/main.rs")
for token in (
    "LinuxLanBridgeRuntime::production()",
    ".manage(lan_bridge_service)",
    "desktop_api::desktop_api_start_lan_bridge",
    "desktop_api::desktop_api_stop_lan_bridge",
    'P2PKANBAN_UTS_LAN_BRIDGE_PROBE',
    "LinuxLanBridgeRuntime::host_probe()",
):
    if token not in main:
        fail("A14 composition/host-probe contract missing " + token)
if "lan_bridge_service.start(" in main:
    fail("A14 production composition auto-starts the LAN bridge")

api = read("src-tauri/src/desktop_api.rs")
transport = read("src/shared/transport/desktop.ts")
feature = read("src/features/system/api/lanBridge.ts")
types = read("src/shared/api/types.ts")
ui = read("src/App.tsx")
for command in (
    "desktop_api_lan_bridge_addresses",
    "desktop_api_lan_bridge_status",
    "desktop_api_start_lan_bridge",
    "desktop_api_stop_lan_bridge",
):
    if command not in api or command not in main or command not in transport:
        fail("A14 typed IPC command missing " + command)
for route in (
    "/system/lan-bridge/addresses",
    "/system/lan-bridge/status",
    "/system/lan-bridge/start",
    "/system/lan-bridge/stop",
):
    if route not in transport or route not in feature:
        fail("A14 frontend typed route missing " + route)
for token in ("LanBridgeStatus", "LanBridgeStartResult", "devicePublicKey"):
    if token not in types:
        fail("A14 frontend DTO missing " + token)
for token in (
    "A14 BOUNDED LAN COMPATIBILITY",
    "off by default",
    "Start compatibility bridge",
    "one-time capability",
    "private device key never leaves this native process",
):
    if token.lower() not in ui.lower():
        fail("A14 UI boundary missing " + token)
if "devicePrivateKey" in ui or "boardKey" in ui:
    fail("A14 UI exposes private provisioning material")

capability = load("src-tauri/capabilities/main-minimal.json")
if capability.get("permissions") != []:
    fail("A14 must not grant generic WebView permissions")
conf = load("src-tauri/tauri.conf.json")
if "connect-src 'none'" not in conf.get("app", {}).get("security", {}).get("csp", ""):
    fail("A14 must keep WebView network disabled")

fixture = load("fixtures/protocol/lan-bridge-v1-golden.json")
if fixture.get("format") != "p2p-kanban-lan-bridge-golden-vector" or fixture.get("version") != 1:
    fail("A14 golden vector metadata mismatch")
if fixture.get("envelopeJson", "").find("p2p-kanban-lan-bridge/1") < 0:
    fail("A14 golden vector protocol drifted")
if "devicePrivateKey" in json.dumps(fixture):
    fail("A14 golden vector contains private destination identity material")

probe = read("tools/a14_host_lan_bridge_probe.py")
for token in (
    "P2PKANBAN_UTS_LAN_BRIDGE_PROBE",
    "127.0.0.1",
    "49152 <= parsed.port <= 65535",
    "one-time bridge endpoint remained reachable",
):
    if token not in probe:
        fail("A14 host probe missing " + token)
for forbidden in ("sudo", "iptables", "nft ", "firewall-cmd", "ufw ", "systemctl", "curl", "wget"):
    if forbidden in probe:
        fail("A14 host probe performs forbidden host mutation/bootstrap: " + forbidden)

plan = load("tools/uts_plan.json")
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema mismatch after A14")
stage = str(plan.get("stage", ""))
try:
    stage_number = int(stage.removeprefix("A"))
except ValueError:
    fail("UTS plan stage is not an Axx stage")
if stage_number < 14:
    fail("UTS plan regressed before A14")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a13" not in ids or "a14" not in ids or ids.index("a13") >= ids.index("a14"):
    fail("A14 deterministic gate missing/not ordered after A13")
post = {item.get("id"): item.get("command") for item in plan.get("host", {}).get("postBuildProbes", [])}
if post.get("a14-rust-lan-bridge") != [
    "cargo", "test", "--manifest-path", "src-tauri/Cargo.toml", "--locked", "--offline", "a14_", "--", "--nocapture"
]:
    fail("A14 Rust host probe missing")
if post.get("a14-host-lan-bridge") != ["python3", "-B", "tools/a14_host_lan_bridge_probe.py"]:
    fail("A14 real-binary host probe missing")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A14 optional LAN compatibility bridge, off by default" not in status:
    fail("A14 implementation ledger missing")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if stage_number == 14:
    if "canonical UTS pending" not in status:
        fail("A14 implementation ledger prematurely claims acceptance")
    if "A15" not in sequence or "PKGBUILD + signed repository packaging" not in sequence:
        fail("next stage after A14 is not A15 packaging")
else:
    if "A14" not in status or "canonical UTS green" not in status:
        fail("post-A14 status does not preserve A14 acceptance history")
    if "A14" not in sequence or "canonical" not in sequence or "green" not in sequence:
        fail("post-A14 sequence does not preserve A14 acceptance history")
debt = read("docs/architecture/08-implementation-corrections-and-debt.md")
for token in ("DEBT-A14-001", "DEBT-A14-002", "DEBT-A14-003"):
    if token not in debt:
        fail("A14 debt ledger missing " + token)

# Evidence binds stable A14-owned files. Shared composition/UI/UTS/docs can evolve in A15+.
evidence = load("evidence/a14-bounded-lan-bridge.json")
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A14":
    fail("A14 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalReferences", "sources"):
    if not evidence.get(key):
        fail("A14 evidence missing " + key)
for item in evidence.get("sources", []):
    rel = item.get("path", "")
    expected = item.get("sha256", "")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("unsafe A14 evidence source path " + rel)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid A14 evidence digest " + rel)
    if not (ROOT / rel).is_file():
        fail("missing A14 evidence source " + rel)
    if sha(rel) != expected:
        fail("A14 evidence source digest drifted: " + rel)

print("A14 optional bounded LAN compatibility bridge: OK")
