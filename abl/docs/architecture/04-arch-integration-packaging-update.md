# 04 — Arch integration, packaging, install, update, rollback and uninstall

## 1. Platform contract

**Target GA:** current Arch Linux x86_64, tested on KDE Plasma and GNOME under Wayland plus one X11 session. EndeavourOS/Manjaro-class distributions are compatibility targets, not identical package universes; support is conditional on meeting declared runtime dependencies.

**[FACT]** Arch is rolling-release and explicitly does not support partial upgrades. The application must never recommend or automate `pacman -Sy`-style partial update states.

## 2. WebKitGTK/runtime dependency

**[FACT]** Tauri 2 on Linux uses the system WebKitGTK stack and documents Arch prerequisites including `webkit2gtk-4.1` plus normal build dependencies.

**[PROPOSAL]** The primary pacman package declares runtime libraries explicitly instead of bundling a private browser engine. This accepts rolling ABI/runtime churn in exchange for lower duplicate footprint and system-owned security updates.

### Failure handling
- detect WebKitGTK initialization failure before presenting a blank window;
- write a small native/stderr diagnostic including package/version checks and recovery guidance;
- do not download arbitrary runtime libraries into `$HOME` to bypass package ownership;
- current-system breakage after a library transition is handled through package rebuild/update, not private `LD_LIBRARY_PATH` hacks.

## 3. XDG and desktop integration

### Files
- data: `$XDG_DATA_HOME/p2pkanban`;
- config: `$XDG_CONFIG_HOME/p2pkanban`;
- state/logs: `$XDG_STATE_HOME/p2pkanban`;
- cache: `$XDG_CACHE_HOME/p2pkanban`;
- runtime sockets/locks if needed: `$XDG_RUNTIME_DIR/p2pkanban` only, never persistent state.

### Desktop entry
Install a version-controlled `.desktop` entry under `/usr/share/applications/` through the package, with:
- stable desktop ID;
- icon names from `/usr/share/icons/hicolor/...`;
- declared deep-link scheme (e.g. `x-scheme-handler/p2pkanban`) only after handler validation is implemented;
- no shell interpolation of untrusted URL values.

### File associations
Portable bundle/import MIME association may be added later with a dedicated MIME type. Opening a file from the shell must route through the existing single instance and validate format before mutation.

## 4. Wayland + X11

### Wayland
Primary test path. Avoid X11-only global APIs. File pickers/open/save should prefer native Tauri/portal integration where practical. Clipboard, drag/drop, window focus and tray behavior must be tested on KWin and Mutter.

### X11
Supported compatibility path. Do not build product features that require X11 global hotkeys/window enumeration unless separately justified.

### Rendering regression policy
Record at diagnostics time:
- session type (`WAYLAND_DISPLAY`/`DISPLAY`, sanitized);
- desktop environment/session name;
- WebKitGTK runtime version;
- GPU/render backend only if obtainable without collecting sensitive hardware IDs.

## 5. Notifications

Use the freedesktop Desktop Notifications D-Bus service when available. Notifications are a convenience layer; failed notification delivery must never change reminder/sync correctness.

Rules:
- reminders remain stored durably independent of notification service;
- clicking a notification sends a validated application intent;
- avoid embedding secret/card content in notification payload by default when screen privacy is a concern; provide preference;
- if no notification daemon exists, show in-app status/history instead of crashing.

## 6. Tray / StatusNotifierItem

**[PROPOSAL]** tray is opt-in and capability-detected. Use StatusNotifierItem semantics where supported. GNOME environments without a visible tray host are expected; absence is not an error.

If “close to tray” is enabled but no usable host exists, closing the last window must follow an explicit configured behavior and show a one-time explanation, not leave a mysterious headless process.

## 7. Secret Service / KWallet / keyring absence

The app speaks the Secret Service API rather than hardcoding a GNOME or KDE implementation. KDE/KWallet compatibility depends on the installed provider/bridge; test it explicitly. Minimal window managers may have no provider.

Never install/start a keyring daemon or alter PAM/session configuration automatically. Offer passphrase/session-only fallback from the application.

## 8. Decision A-OS-003 — no systemd user service by default

**Decision.** v1 installs/enables no `systemd --user` unit. Application lifetime follows the foreground process and an explicit tray choice. A future background-sync service requires its own ADR and explicit opt-in; a root/system service remains out of scope.

**Grounds.** The least-sufficient desktop client already owns local commits and opportunistic synchronization in-process. A user service would add a second lifecycle, session D-Bus/keyring edge cases, DB writer arbitration, upgrade coordination and invisible idle power/network use before a product requirement proves those costs worthwhile.

**Rejected alternatives.** (1) always-on user daemon; (2) automatically enabled user unit; (3) `loginctl enable-linger` to keep sync alive after logout; (4) root/system daemon. All enlarge privilege/lifecycle surface and contradict the normal native-app expectation.

**Costs.** With v1 closed, synchronization stops until the app is launched again. Users who explicitly want background behavior must keep the app/tray process running.

**Failure modes.** Accidental headless process after closing the window; future daemon and UI both opening the SQLite writer; service starting without usable session keyring/D-Bus; package update while an old daemon remains resident; excessive background wakeups.

**Verification.** Fresh install has no enabled p2pKanban unit; `systemctl --user` inspection shows no required daemon; closing the process releases DB/socket/lock resources; tray mode is explicit and measurable; no `loginctl enable-linger` or root service is invoked. If a future optional service is proposed, its ADR must cover `/usr/lib/systemd/user/` packaging, authenticated UI↔daemon IPC, single-writer ownership, keyring/session-bus availability, update coordination and explicit enable/disable commands.

## 9. Network switching, suspend and resume

Linux network stack may be NetworkManager, systemd-networkd or something else. Do not depend on one manager for correctness.

Use a layered strategy:
- transport errors and timers are authoritative;
- optional network-state signals can accelerate reconnect but must not be required;
- on resume, tear down stale relay/P2P sessions and perform bounded idempotent catch-up;
- VPN changes, DNS failure, captive portal and IPv4/IPv6 transitions must not block local commits;
- background retry has exponential backoff/jitter and stops producing wakeups when fully offline/asleep.

## 10. Firewall / LAN discovery

Normal operation is outbound-only and requires no firewall changes.

For an explicit temporary LAN bridge:
- first attempt user-visible bind without modifying firewall;
- if blocked, provide manual distro/firewall guidance only after diagnosis;
- never execute `nft`, `iptables`, `firewall-cmd`, `ufw` or polkit authorization automatically;
- multicast/mDNS discovery, if added, is separately permissioned and feature-gated because it adds network visibility and wakeups.

## 11. Packaging channels

### Primary — signed pacman repository package
Artifact: `p2pkanban-<version>-x86_64.pkg.tar.zst` plus detached/package database signatures according to repository policy.

Package owns immutable application files under `/usr`:
```text
/usr/bin/p2pkanban
/usr/lib/p2pkanban/...          # packaged resources if needed
/usr/share/applications/...
/usr/share/icons/hicolor/...
/usr/share/licenses/p2pkanban/...
```

Mutable profile data remains entirely under the user's XDG directories.

### PKGBUILD / AUR route
Maintain a readable PKGBUILD that uses fixed source version/checksums and can build in a clean chroot. If published in AUR, treat AUR as a build-recipe distribution channel, not a binary trust root. Release CI and official signed packages remain independently verifiable.

### AppImage fallback
Use for users who cannot configure the repository or need a portable rescue artifact. Trade-offs:
- larger artifact/duplicated libraries;
- FUSE/extraction differences;
- more complex desktop integration/update ownership;
- still depends on host kernel/glibc baseline and some system integration libraries;
- must not become an excuse to bundle stale WebKit/crypto indefinitely.

Provide an extraction/run fallback if FUSE is unavailable, but do not require privileged FUSE setup.

### Flatpak
**[EXPERIMENT-NEEDED]** potentially useful later for sandboxing/portable runtime, but it changes portal/keyring/network/update assumptions and should be evaluated as a separate distribution target, not silently substituted for Arch-native package behavior.

## 12. Install semantics

### pacman/repository install
- package manager writes `/usr` files;
- post-install scriptlets, if any, must be minimal and never mutate user profiles;
- first run creates XDG directories as the user;
- no root helper/service/database initialization;
- no network required for first launch after package + dependencies are installed.

### Offline installation bundle
For restricted networks produce a documented release bundle containing:
- signed p2pKanban package;
- signature/public-key verification instructions;
- optional dependency package cache manifest for a known Arch snapshot/current repository state;
- checksums/SBOM/source manifest;
- recovery AppImage if chosen for that release.

Do **not** prescribe installing arbitrary old dependency sets onto a newer partially upgraded system. Offline bundle instructions must keep the system internally consistent.

## 13. Update model

### pacman-owned install
**Decision →** application checks may notify that a newer version exists, but the package manager performs the actual `/usr` update.

**Grounds →** pacman owns files/dependencies and Arch expects coherent system upgrades.

**Rejected alternatives →** app self-overwriting `/usr`; private background updater; `sudo` prompt from the UI; automated `pacman -Sy`.

**Costs →** release availability depends on repository/package publication; package update may accompany broader system update.

**Failure modes →** stale mirror, key expiration, dependency soname transition, user pins/holds package, incompatible partial-upgrade state.

**Verification →** clean fully updated VM; repo signing; `pacman -Qkk`; upgrade/downgrade rehearsal; no app process writes `/usr`.

### AppImage channel
AppImage may use app-owned update checks only if the exact artifact is verified by a signed release manifest and hash before atomic replacement. Never mix AppImage self-update semantics with pacman-owned installs.

## 14. Schema update + package rollback

Package downgrade and database downgrade are different operations.

Rules:
- before a schema migration, create verified SQLite backup;
- metadata declares min reader/writer versions;
- keep migrations expand/contract-compatible while N-1 rollback is promised;
- if new app startup/migration fails, restore the pre-migration DB before running old binary where required;
- `pacman -U /var/cache/pacman/pkg/...` alone is not advertised as safe data rollback without schema compatibility proof;
- diagnostics must distinguish package rollback from profile restore.

## 15. Uninstall and data semantics

`pacman -R p2pkanban` removes package-owned `/usr` files only. It does not delete `$XDG_DATA_HOME`, `$XDG_CONFIG_HOME`, `$XDG_STATE_HOME` or secrets.

Provide an in-app/export-first **Delete local profile/data** operation for explicit purge. If a user later manually deletes profile directories, document which keyring entries to remove; do not add destructive package post-remove hooks.

This preserves reinstall/recovery and conforms to package ownership expectations.

## 16. Rolling-release/ABI strategy

- build official package in a controlled clean Arch chroot;
- test against current supported repository state, not arbitrary old frozen Arch installations;
- declare direct dynamic dependencies through package metadata;
- run ABI/dependency smoke after major WebKitGTK/OpenSSL/GTK/glibc transitions;
- rebuild promptly on soname/API changes;
- record build environment/package lock manifest in release evidence;
- never use private copied system libraries merely to keep an obsolete build alive.

## 17. Arch ARM feasibility

**[EXPERIMENT-NEEDED]** Do not promise ARM64/Arch Linux ARM GA until all of the following pass on real hardware or representative builders:
- Rust/Tauri target build;
- WebKitGTK/runtime availability;
- crypto/SQLite dependencies;
- packaging/repository path;
- performance/power baseline;
- Nostr/Iroh transport tests.

The architecture is conceptually portable, but packaging/support evidence is currently x86_64-first.
