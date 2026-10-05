#!/usr/bin/env python3
"""Deterministic/network-free A06 XDG + profile instance-control gate."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A06 CHECK FAILED: " + message)


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail("missing " + rel)
    return path.read_text(encoding="utf-8")


required = (
    "src-tauri/src/infrastructure/profile.rs",
    "src-tauri/src/infrastructure/linux/mod.rs",
    "src-tauri/src/infrastructure/linux/xdg.rs",
    "src-tauri/src/infrastructure/linux/instance.rs",
    "tools/a06_host_instance_probe.py",
    "docs/architecture/adr/ADR-007-profile-instance-control.md",
    "docs/evidence/A06_XDG_INSTANCE_CONTROL.md",
)
for rel in required:
    read(rel)

cargo = read("src-tauri/Cargo.toml")
if 'libc = "=0.2.189"' not in cargo:
    fail("Linux flock dependency must be exact-pinned")
plan_stage = json.loads(read("tools/uts_plan.json")).get("stage")
for token in ("systemd", "dbus", "nix =", "fs2 ="):
    if token in cargo.lower():
        fail("A06 introduced an unnecessary platform/runtime dependency: " + token)
if plan_stage in {"A06", "A07", "A07b", "A08", "A09", "A09b", "A10", "A11", "A12"} and "zbus" in cargo.lower():
    fail("zbus is not allowed before the A13 Linux integration stage")

profile = read("src-tauri/src/infrastructure/profile.rs")
for token in (
    'root.join("profile.db")',
    'root.join("backups")',
    'root.join("migration-journal.json")',
    'format!("pre-migration-v{from_version}.sqlite")',
    "mode(0o700)",
    "mode(0o600)",
    "sync_all()",
):
    if token not in profile:
        fail("profile storage contract missing " + token)

xdg = read("src-tauri/src/infrastructure/linux/xdg.rs")
for token in (
    '"XDG_DATA_HOME"',
    '[".local", "share"]',
    '"XDG_CONFIG_HOME"',
    '[".config"]',
    '"XDG_STATE_HOME"',
    '[".local", "state"]',
    '"XDG_CACHE_HOME"',
    '[".cache"]',
    '"XDG_RUNTIME_DIR"',
    'data_root.join("profiles").join(profile_name)',
    'root.join("instances").join(format!("{}.sock", self.paths.profile_name))',
    "metadata.uid() != unsafe { libc::geteuid() }",
    "metadata.permissions().mode() & 0o077",
    "metadata.file_type().is_symlink()",
    "RuntimeStatus::Missing",
    "RuntimeStatus::Unsafe",
    "RuntimeStatus::Unwritable",
    "invalid_profile_name_cannot_escape_profile_root",
    "missing_runtime_dir_degrades_without_breaking_profile_paths",
    "unwritable_persistent_root_fails_closed_for_non_root_user",
):
    if token not in xdg:
        fail("XDG/runtime capability contract missing " + token)

instance = read("src-tauri/src/infrastructure/linux/instance.rs")
for token in (
    "libc::flock",
    "libc::LOCK_EX | libc::LOCK_NB",
    "libc::LOCK_UN",
    'ACTIVATE_MAIN_V1: &[u8] = b"activate-main-v1\\n"',
    "UnixDatagram::bind",
    "UnixDatagram::unbound",
    "SecondaryInstance::RoutingUnavailable",
    "concurrent_second_instance_is_routed_to_primary",
    "missing_runtime_keeps_writer_lock_but_routes_nothing",
    "stale_runtime_socket_is_replaced_only_after_writer_lock_is_owned",
    "kernel_lock_is_released_after_abnormal_child_exit",
):
    if token not in instance:
        fail("instance-control contract missing " + token)
for forbidden in ("TcpListener", "TcpStream", "localhost", "127.0.0.1", "systemctl", "sudo", "polkit"):
    if forbidden.lower() in instance.lower():
        fail("forbidden A06 instance assumption/API: " + forbidden)

migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
for token in (
    "ProfileStoragePaths",
    "layout.migration_backup(from)",
    "layout.migration_journal()",
    "write_private_file",
    "enforce_database_permissions",
    'conn.backup("main", &backup, None)?;',
    'conn.restore("main", &backup, None::<fn(rusqlite::backup::Progress)>)?;',
    "migration_artifacts_use_final_profile_recovery_layout",
):
    if token not in migration:
        fail("A05 migration was not safely moved into final A06 layout: " + token)
for obsolete in ("fn sidecar_path", "fn backup_path", "fn journal_path"):
    if obsolete in migration:
        fail("temporary A05 sidecar path helper survived A06: " + obsolete)

repo = read("src-tauri/src/infrastructure/sqlite/repository.rs")
if "pub fn open(layout: &ProfileStoragePaths)" not in repo:
    fail("SQLite repository does not consume the profile storage layout")
if "SqlitePlannerRepository::open(&layout)" not in repo:
    fail("SQLite reopen test is not layout-aware")

main = read("src-tauri/src/main.rs")
for token in (
    'DesktopPaths::resolve(&XdgEnvironment::current(), "default")',
    "instance::acquire(&prepared)",
    "InstanceRole::Secondary(SecondaryInstance::Routed)",
    "InstanceRole::Secondary(SecondaryInstance::RoutingUnavailable)",
    ".manage(primary)",
    ".manage(diagnostics)",
    'handle.get_webview_window("main")',
    "window.show()",
    "window.set_focus()",
):
    if token not in main:
        fail("native startup is not wired to A06 instance/XDG behavior: " + token)
if main.index("instance::acquire(&prepared)") > main.index("tauri::Builder::default()"):
    fail("profile writer ownership must be acquired before Tauri starts")

desktop_api = read("src-tauri/src/desktop_api.rs")
desktop_transport = read("src/shared/transport/desktop.ts")
api_types = read("src/shared/api/types.ts")
for token in ("desktop_api_profile_diagnostics", "profile_diagnostics_to_wire", "runtimeActivation"):
    if token not in desktop_api:
        fail("typed profile diagnostics command missing " + token)
for token in ("/system/profile-diagnostics", "DESKTOP_PROFILE_DIAGNOSTICS_COMMAND", "ProfileDiagnostics"):
    if token not in desktop_transport:
        fail("desktop transport does not expose typed diagnostics route: " + token)
if "export interface ProfileDiagnostics" not in api_types:
    fail("frontend diagnostics DTO is missing")

host_probe = read("tools/a06_host_instance_probe.py")
for token in (
    "activation routed to the primary instance",
    "writer ownership is protected but XDG runtime activation routing is unavailable",
    "XDG_RUNTIME_DIR",
    "assert_primary_stays_running",
):
    if token not in host_probe:
        fail("real-binary A06 host probe missing " + token)
for forbidden_exec in (
    '["sudo"', "['sudo'", '["systemctl"', "['systemctl'", '["pacman"', "['pacman'",
    '["curl"', "['curl'", '["wget"', "['wget'",
):
    if forbidden_exec in host_probe:
        fail("A06 host probe must not execute privileged/network bootstrap command: " + forbidden_exec)
for network_api in ("urllib.request", "requests.get", "requests.post", "http.client"):
    if network_api in host_probe:
        fail("A06 host probe must not contain network client API: " + network_api)

# No implementation file may hard-code package-owned or per-user absolute paths.
for rel in (
    "src-tauri/src/infrastructure/profile.rs",
    "src-tauri/src/infrastructure/linux/xdg.rs",
    "src-tauri/src/infrastructure/linux/instance.rs",
    "src-tauri/src/infrastructure/sqlite/migration.rs",
    "src-tauri/src/main.rs",
):
    lowered = read(rel).lower()
    for forbidden in ('"/usr', '"/home/', "~/.local", "~/.config", "~/.cache"):
        if forbidden in lowered:
            fail(f"hard-coded host path leaked into {rel}: {forbidden}")

# Older gates must protect their own stage without freezing progression at A05/A05b.
a05 = read("tools/check_a05.py")
if "exact next architecture patch is **A06" in a05:
    fail("A05 checker still freezes NEXT_PATCH_SEQUENCE at A06")
a05b = read("tools/check_a05b.py")
if 'plan.get("stage") != "A05b"' in a05b or "A06 must remain the next architecture patch" in a05b:
    fail("A05b checker still freezes repository progression")

plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1:
    fail("unsupported UTS plan schema")
ids = [item.get("id") for item in plan.get("deterministic", [])]
for required_id in ("a05", "a05b", "a06"):
    if required_id not in ids:
        fail("missing deterministic gate " + required_id)
if not ids.index("a05") < ids.index("a05b") < ids.index("a06"):
    fail("A06 deterministic gate order is wrong")
post = plan.get("host", {}).get("postBuildProbes", [])
if not any(item.get("id") == "a06-instance" and item.get("command") == ["python3", "-B", "tools/a06_host_instance_probe.py"] for item in post):
    fail("UTS plan does not run the real-binary A06 instance probe")
verifier = read("tools/uts_verify.py")
if 'host.get("postBuildProbes", [])' not in verifier:
    fail("UTS verifier does not execute stage-owned post-build probes")

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((line for line in status.splitlines() if "A06 XDG adapters + multi-instance/locking behavior" in line), "")
if "**implemented" not in line or "A07" not in line:
    fail("implementation ledger did not advance A06 to implemented/A07")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A07" not in sequence:
    fail("next-patch sequence lost the A07 architecture stage")
adr = read("docs/architecture/adr/ADR-007-profile-instance-control.md")
evidence = read("docs/evidence/A06_XDG_INSTANCE_CONTROL.md")
for token in ("flock", "XDG_RUNTIME_DIR", "RoutingUnavailable", "A07"):
    if token not in adr + evidence:
        fail("A06 SSOT/evidence missing " + token)

print("A06 XDG profile + instance control: OK")
