#!/usr/bin/env python3
"""Deterministic/network-free A13 Linux lifecycle/integration gate."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A13 CHECK FAILED: " + message)


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
    "src-tauri/src/domain/integration.rs",
    "src-tauri/src/application/integration.rs",
    "src-tauri/src/infrastructure/linux/integration.rs",
    "src/features/system/api/integration.ts",
    "tools/a13_host_integration_probe.py",
    "docs/evidence/A13_DESKTOP_INTEGRATION.md",
    "evidence/a13-desktop-integration.json",
]
for rel in required:
    if not (ROOT / rel).is_file():
        fail("missing " + rel)

cargo = tomllib.loads(read("src-tauri/Cargo.toml"))
deps = cargo.get("dependencies", {})
zbus = deps.get("zbus")
if not isinstance(zbus, dict) or zbus.get("version") != "=5.19.0":
    fail("A13 must directly pin the already-resolved zbus 5.19.0 line")
if zbus.get("default-features") is not False or set(zbus.get("features", [])) != {"blocking-api", "tokio"}:
    fail("A13 zbus feature boundary drifted")
tauri = deps.get("tauri", {})
if tauri.get("features") != []:
    fail("A13 must detect tray capability without enabling a tray lifecycle/API")
for forbidden in ("notify-rust", "tauri-plugin-notification", "tauri-plugin-deep-link"):
    if forbidden in deps:
        fail("A13 added an unnecessary integration plugin: " + forbidden)

# Storage/protocol remain unchanged at schema v6.
migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
if "CURRENT_SCHEMA_VERSION: u32 = 6" not in migration:
    fail("A13 must not advance the SQLite schema")
if (ROOT / "src-tauri/migrations/0007_desktop_integration.sql").exists():
    fail("A13 must not persist desktop capabilities/deep-link queue in SQLite")

domain = read("src-tauri/src/domain/integration.rs")
for token in [
    "MAX_DEEP_LINK_BYTES: usize = 512",
    'DEEP_LINK_ACTIVATION_PREFIX: &[u8] = b"deep-link-v1\\t"',
    "SessionKind",
    "CapabilityState",
    "IntegrationCapabilities",
    "DeepLinkTarget",
    "parse_deep_link",
    '"p2pkanban://activate"',
    '"workspace" => DeepLinkTarget::Workspace',
    '"board" => DeepLinkTarget::Board',
    '"card" => DeepLinkTarget::Card',
    "a13_deep_links_fail_closed_on_untrusted_url_shapes",
]:
    if token not in domain:
        fail("A13 domain contract missing " + token)
for forbidden in ("zbus", "tauri::", "rusqlite", "std::fs", "std::process", "Command::new"):
    if forbidden in domain:
        fail("A13 domain leaked platform/runtime detail: " + forbidden)
for unsafe_acceptor in ('strip_prefix("http://")', 'strip_prefix("https://")', 'strip_prefix("file://")', 'strip_prefix("javascript:")'):
    if unsafe_acceptor in domain:
        fail("A13 deep-link parser accepts forbidden generic scheme: " + unsafe_acceptor)
if '"https://example.invalid/"' not in domain:
    fail("A13 deep-link tests must prove a generic HTTPS URL is rejected")

app = read("src-tauri/src/application/integration.rs")
for token in [
    "pub trait IntegrationAdapter",
    "pub struct IntegrationService",
    "pending_deep_links: Mutex<VecDeque<DeepLinkIntent>>",
    "if pending.len() >= 32",
    "pub fn take_deep_links",
    "a13_integration_capabilities_degrade_without_becoming_requirements",
    "a13_deep_link_queue_is_bounded_and_drain_only",
]:
    if token not in app:
        fail("A13 application boundary missing " + token)
for forbidden in ("zbus", "tauri::", "std::fs", "std::process", "rusqlite"):
    if forbidden in app:
        fail("A13 application layer leaked Linux adapter detail: " + forbidden)

linux = read("src-tauri/src/infrastructure/linux/integration.rs")
for token in [
    "Connection::session()",
    "DBusProxy::new(&connection)",
    "proxy.name_has_owner(bus_name)",
    '"org.freedesktop.Notifications"',
    '"org.kde.StatusNotifierWatcher"',
    '"org.freedesktop.portal.Desktop"',
    "XDG_SESSION_TYPE",
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "sanitize_desktop_name",
    "a13_session_detection_prefers_declared_wayland_and_x11",
]:
    if token not in linux:
        fail("A13 Linux capability adapter missing " + token)
for forbidden in ("start_service_by_name", "request_name(", "systemctl", "loginctl", "notify-send", "dbus-send"):
    if forbidden in linux:
        fail("A13 capability detection must not start/claim external services: " + forbidden)

instance = read("src-tauri/src/infrastructure/linux/instance.rs")
for token in [
    'ACTIVATE_MAIN_V1: &[u8] = b"activate-main-v1\\n"',
    "MAX_ACTIVATION_PAYLOAD_BYTES: usize = 1024",
    "pub fn route_payload(paths: &PreparedDesktopPaths, payload: &[u8]) -> bool",
    "payload.len() > MAX_ACTIVATION_PAYLOAD_BYTES",
    "a13_activation_payload_is_bounded_and_uses_existing_socket",
]:
    if token not in instance:
        fail("A13 did not safely extend A06 activation routing: " + token)
for forbidden in ("TcpListener", "UdpSocket", "0.0.0.0", "127.0.0.1"):
    if forbidden in instance:
        fail("A13 deep-link routing must remain on the A06 Unix socket: " + forbidden)

main = read("src-tauri/src/main.rs")
for token in [
    "instance::acquire(&prepared)",
    "encode_deep_link_activation(intent)",
    "instance::route_payload(&prepared, &payload)",
    "decode_deep_link_activation(payload)",
    ".manage(integration_service)",
    "desktop_api::desktop_api_integration_capabilities",
    "desktop_api::desktop_api_take_deep_link_intents",
    '"--integration-capabilities-json"',
    '"trayLifecycle": "disabled"',
    '"systemdUserService": "disabled"',
]:
    if token not in main:
        fail("A13 runtime composition missing " + token)
if main.index("instance::acquire(&prepared)") > main.index("SqliteWorkspaceCatalog::open(&prepared.paths.profile)"):
    fail("A13 must preserve A06 writer lock before durable profile open")
for forbidden in ("systemctl", "loginctl", "TrayIconBuilder", "notify_send", "Command::new"):
    if forbidden in main:
        fail("A13 silently expanded foreground lifecycle: " + forbidden)

api = read("src-tauri/src/desktop_api.rs")
for token in [
    "desktop_api_integration_capabilities",
    "desktop_api_take_deep_link_intents",
    "integration_capabilities_to_wire",
    "deep_link_intent_to_wire",
    '"trayLifecycle"',
    '"systemdUserService"',
]:
    if token not in api:
        fail("A13 typed IPC missing " + token)
for forbidden in ("zbus", "DBusProxy", "std::process", "Command::new", "std::fs", "File::open"):
    if forbidden in api:
        fail("WebView IPC gained generic OS privilege: " + forbidden)

transport = read("src/shared/transport/desktop.ts")
types = read("src/shared/api/types.ts")
feature = read("src/features/system/api/integration.ts")
ui = read("src/App.tsx")
for route in ("/system/integration-capabilities", "/system/deep-link-intents/take"):
    if route not in transport or route not in feature:
        fail("A13 frontend typed route missing " + route)
for token in ("IntegrationCapabilities", "DeepLinkIntentSummary"):
    if token not in types:
        fail("A13 frontend DTO missing " + token)
for token in (
    "A13 lifecycle/integration",
    "Desktop integration capabilities",
    "Validated deep-link intents",
    "tray lifecycle:",
    "systemd user service:",
    "Refresh integration",
):
    if token not in ui:
        fail("A13 UI capability surface missing " + token)

capability = load("src-tauri/capabilities/main-minimal.json")
if capability.get("permissions") != []:
    fail("A13 must not grant generic WebView permissions")
conf = load("src-tauri/tauri.conf.json")
if "connect-src 'none'" not in conf.get("app", {}).get("security", {}).get("csp", ""):
    fail("A13 must keep WebView network disabled")
if "trayIcon" in json.dumps(conf):
    fail("A13 detects tray host capability but must not create tray lifecycle yet")

# A13 itself must not smuggle package/service registration into the runtime source.
# A15+ may add exactly the package-owned desktop association that routes into the
# already validated A13 argv/deep-link path. A systemd service remains forbidden.
plan = load("tools/uts_plan.json")
if plan.get("schemaVersion") != 1:
    fail("UTS plan schema mismatch after A13")
stage = str(plan.get("stage", ""))
try:
    stage_number = int(stage.removeprefix("A"))
except ValueError:
    fail("UTS plan stage is not an Axx stage")
if stage_number < 13:
    fail("UTS plan regressed before A13")

for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith((".git/", "node_modules/", "dist/", "src-tauri/target/", ".uts-reports/")):
        continue
    if path.suffix == ".service":
        fail("A13 foreground lifecycle must not gain a systemd service: " + rel)
    if path.suffix == ".desktop":
        if stage_number < 15 or rel != "packaging/arch/p2pkanban.desktop":
            fail("unexpected desktop integration artifact after A13: " + rel)

probe = read("tools/a13_host_integration_probe.py")
for token in [
    "--integration-capabilities-json",
    "DBUS_SESSION_BUS_ADDRESS",
    "p2pkanban://board/not-a-uuid",
    "validated deep link routed to the primary instance",
    "accepted validated deep-link target=board",
    "trayLifecycle",
    "systemdUserService",
]:
    if token not in probe:
        fail("A13 real-binary host probe missing " + token)
for forbidden_exec in (
    '["sudo"', "['sudo'",
    '["systemctl"', "['systemctl'",
    '["loginctl"', "['loginctl'",
    '["pacman"', "['pacman'",
    '["curl"', "['curl'",
    '["wget"', "['wget'",
    "requests.", "urllib.request",
):
    if forbidden_exec in probe:
        fail("A13 host probe contains forbidden bootstrap/action: " + forbidden_exec)

ids = [item.get("id") for item in plan.get("deterministic", [])]
if "a12" not in ids or "a13" not in ids or ids.index("a12") >= ids.index("a13"):
    fail("A13 deterministic gate missing/not ordered after A12")
post = {item.get("id"): item.get("command") for item in plan.get("host", {}).get("postBuildProbes", [])}
if post.get("a13-rust-integration") != [
    "cargo", "test", "--manifest-path", "src-tauri/Cargo.toml", "--locked", "--offline", "a13_", "--", "--nocapture"
]:
    fail("A13 Rust host contract probe missing")
if post.get("a13-desktop-integration") != ["python3", "-B", "tools/a13_host_integration_probe.py"]:
    fail("A13 real-binary integration probe missing")

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A13 Wayland/X11 + notifications/deep links/tray capability detection" not in status:
    fail("A13 implementation status missing")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if stage_number == 13:
    if "A14" not in sequence or "optional bounded LAN compatibility bridge" not in sequence:
        fail("next stage after A13 is not A14 LAN compatibility bridge")
else:
    if "A13" not in sequence or "canonical Cargo/runtime UTS" not in sequence or "green" not in sequence:
        fail("post-A13 sequence does not preserve A13 acceptance history")
debt = read("docs/architecture/08-implementation-corrections-and-debt.md")
for token in ("DEBT-A13-001", "DEBT-A13-002", "DEBT-A13-003"):
    if token not in debt:
        fail("A13 debt ledger missing " + token)

# Evidence binds A13-owned source. Later stages may extend composition/UI but not rewrite this evidence silently.
evidence = load("evidence/a13-desktop-integration.json")
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A13":
    fail("A13 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalReferences", "sources"):
    if not evidence.get(key):
        fail("A13 evidence missing " + key)
evolving_after_a13 = {
    "src-tauri/Cargo.toml",
    "src-tauri/src/main.rs",
    "src-tauri/src/desktop_api.rs",
    "src/shared/api/types.ts",
    "src/shared/transport/desktop.ts",
    "src/App.tsx",
    "src/styles.css",
    "tools/check_a13.py",
    "tools/uts_plan.json",
    "docs/architecture/08-implementation-corrections-and-debt.md",
    "docs/IMPLEMENTATION_STATUS.md",
    "docs/NEXT_PATCH_SEQUENCE.md",
}
for item in evidence.get("sources", []):
    rel = item.get("path", "")
    expected = item.get("sha256", "")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("unsafe A13 evidence source path " + rel)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid A13 evidence digest " + rel)
    if not (ROOT / rel).is_file():
        fail("missing A13 evidence source " + rel)
    if rel not in evolving_after_a13 and sha(rel) != expected:
        fail("A13 evidence source digest drifted: " + rel)

print("A13 Linux desktop lifecycle/integration capability detection: OK")
