# 02 — Requirements, non-goals, options and primary ADRs: Arch Linux

## Requirements

### Product/data
- Full local planner read/write without network after profile provisioning.
- Preserve IDs, tombstones, capability epochs, deterministic merge and supported import/export semantics.
- Coexist with current web/backend and Android nodes through explicit protocol/version contracts.
- Recover from crash, failed migration, relay outage and rolling-system change without silently discarding local edits.

### Arch/desktop
- Arch Linux x86_64 is the GA reference; current EndeavourOS/Manjaro-class systems are compatibility targets subject to their package versions.
- Wayland and X11 sessions supported.
- No root privilege for normal runtime.
- Correct XDG storage locations.
- No Docker/Podman/PostgreSQL/Node runtime requirement.
- Missing notification/tray/portal/keyring services degrade gracefully.
- package install/update respects pacman ownership and avoids unsupported partial upgrades.
- default runtime contains no systemd user daemon and no inbound listener.

### Security
- Least-privilege typed IPC.
- Explicit secret vault with no plaintext fallback.
- Signed/verifiable package/update provenance.
- Relay considered untrusted.
- import/link data validated before commit.
- schema downgrade/rollback gates.

### Constrained-network/supply chain
- Installed application remains functional offline.
- Build inputs can be mirrored/vendored/cache-exported.
- No runtime dependence on Docker Hub or a single npm/crates/binary CDN.
- No signature/TLS bypasses as “regional availability” workarounds.

## Non-goals for first GA

- Universal Linux distribution support.
- Bundling PostgreSQL or a container engine.
- Full GTK/Qt UI rewrite.
- Mandatory always-on background sync.
- Automatic `nftables`/firewalld/polkit changes.
- Automatic `loginctl enable-linger`.
- App-controlled system package upgrades/downgrades.
- Support for Arch partial-upgrade states.
- Making AppImage the only supported channel.
- Promising Arch ARM before dependency and real-device validation.
- Making Iroh or edge coordinator mandatory.
- Full attachment/blob subsystem before the current product contract defines it.

## UI/runtime decision matrix

Scores: 1 poor, 5 strong; weights reflect this project.

| Criterion | Weight | Tauri+WebKitGTK | Electron | GTK/Qt rewrite | Browser+local backend |
|---|---:|---:|---:|---:|---:|
| reuse current React | 5 | 5 | 5 | 1 | 5 |
| idle footprint objective | 5 | 4 | 2 | 5 | 3 |
| reuse Rust core | 5 | 5 | 3 | 5 | 4 |
| system integration | 4 | 4 | 3 | 5 | 2 |
| no permanent port | 4 | 5 | 5 | 5 | 1 |
| Arch-native package dependency model | 4 | 4 | 2 | 4 | 3 |
| implementation risk/time | 4 | 4 | 4 | 1 | 4 |
| Wayland/X11 maturity burden | 3 | 4 | 4 | 4 | 4 |
| **weighted direction** | | **preferred** | reject | reject now | reject |

The matrix is a decision aid, not empirical benchmark proof.

### D-ARCH-001 — shell

**Decision →** Tauri 2 + existing React/Vite, system WebKitGTK.

**Grounds →** reuse mature UI and Rust while avoiding bundled Chromium; aligns with distro ownership of system WebKitGTK.

**Rejected alternatives →** Electron footprint; GTK/Qt parity rewrite; browser/local HTTP preserves unwanted port/runtime UX.

**Costs →** WebKitGTK behavior must be tracked across a rolling distro; Tauri/Wry integration; frontend transport adapter.

**Failure modes →** WebKitGTK regression after system update; Wayland-specific rendering/input issue; D-Bus/session differences.

**Verification →** rolling-version CI/current VM, Wayland+X11 E2E, memory/power profiling, WebKitGTK package-version diagnostic.

## Storage decision matrix

| Criterion | SQLite | bundled PostgreSQL | JSON/kv local store | embedded PG-compatible experiment |
|---|---:|---:|---:|---:|
| no daemon/runtime | 5 | 1 | 5 | 4 |
| transactions/integrity | 5 | 5 | 2 | 4 |
| operational simplicity | 5 | 1 | 4 | 3 |
| current SQL reuse | 2 | 5 | 1 | 3 |
| backup/recovery | 5 | 4 | 2 | 3 |
| rolling distro burden | 5 | 2 | 5 | 3 |
| maturity | 5 | 5 | varies | varies |
| **result** | **choose** | reject | reject | experiment only |

### D-ARCH-002 — SQLite with repository extraction

**Decision →** separate desktop SQLite schema/migration line behind application/domain repository interfaces.

**Grounds →** [FACT] current SQL uses PostgreSQL-specific features; [PROPOSAL] desktop must have no local DB daemon.

**Rejected alternatives →** bundled PG keeps service/admin burden; JSON/AsyncStorage lacks full-desktop relational/transaction guarantees; PG-compatible embedding adds uncertain dependency.

**Costs →** semantic reimplementation and a substantial conformance suite.

**Failure modes →** hidden PG semantics lost; migration divergence; WAL unsuitable on user-selected network filesystems.

**Verification →** dual repository contracts, migration fixtures, power/crash tests, prohibit/diagnose unsupported remote filesystem placement.

## Packaging decision matrix

| Criterion | pacman package / signed repo | AUR PKGBUILD | AppImage | Flatpak |
|---|---:|---:|---:|---:|
| Arch ownership semantics | 5 | 5 | 2 | 3 |
| system WebKitGTK integration | 5 | 5 | varies | sandboxed runtime |
| offline install bundle | 3 | 2 unless cached | 5 | 2/3 |
| independent publisher updates | 5 with repo | 2 build recipe | 4 | 4 |
| reproducible package path | 5 | 5 | 3 | 4 |
| user friction | 4 | 3 | 5 | 3 |
| rollback fit | pacman/cache/repo | source rebuild | app-owned | Flatpak model |
| **role** | **primary** | **community/source path** | **fallback** | experiment |

### D-ARCH-003 — pacman-owned install

**Decision →** ship `.pkg.tar.zst` from a signed repository and maintain a reviewable PKGBUILD; AUR may expose the recipe/community route. AppImage is a separate fallback channel.

**Grounds →** package manager understands file ownership/dependencies; rolling security fixes should come from the system stack.

**Rejected alternatives →** self-extracting installer writing `/usr`; AppImage-only; mandatory Flatpak.

**Costs →** repository/signing/PKGBUILD maintenance; distro version matrix.

**Failure modes →** dependency transition, stale mirror, incompatible partial-upgrade state, AUR recipe drift.

**Verification →** clean chroot build/install, `namcap`, package ownership test, full-system-updated VM; explicitly reject unsupported partial-upgrade troubleshooting path.

## Lifecycle decision

### D-ARCH-004 — no systemd user service by default

**Decision →** sync/core lifetime follows interactive process; opt-in tray allowed; headless systemd user service deferred.

**Grounds →** lowest idle footprint and avoids complexity around graphical-session D-Bus/keyring availability. Local-first queue makes stopped process acceptable.

**Rejected alternatives →** always-on systemd user unit; system service/root daemon; auto-enabled linger.

**Costs →** no sync while fully closed.

**Failure modes →** user expects background delivery; closing UI stops relay connection.

**Verification →** UX states this behavior; queue resumes reliably; optional future service has separate ADR/security tests.

## Secret-provider decision

### D-ARCH-005 — Secret Service with secure fallback

**Decision →** store/wrap vault root through Secret Service when available/unlocked. Otherwise offer Argon2id-derived KEK + authenticated-encrypted vault protected by explicit user passphrase, or session-only mode. Never silently write plaintext.

**Grounds →** Linux desktop environments vary; headless/minimal Arch may have no keyring. A missing provider is normal, not an excuse to reduce secrecy.

**Rejected alternatives →** plaintext config/SQLite; hard dependency on GNOME Keyring; auto-starting a keyring daemon without user choice.

**Costs →** multiple UX paths, passphrase recovery semantics and provider tests.

**Failure modes →** locked session keyring, provider change, lost passphrase, secret service disappears mid-session.

**Verification →** GNOME/KDE/minimal sessions; present/locked/absent; reboot/relogin; provider migration; secret canary scan.

## Shared-core policy

**[PROPOSAL]** Share Rust domain/protocol/crypto/repository interfaces where that lowers debt. Do not abstract pacman/XDG/D-Bus lifecycle into a fake cross-platform layer if platform behavior becomes harder to reason about. Android remains TS/mobile-native initially; compatibility is established by versioned JSON/golden vectors before considering FFI.
