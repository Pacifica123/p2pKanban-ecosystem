# p2pKanban Arch Linux Native Architecture Blueprint

**Target:** Arch Linux and close Arch-based desktop systems (EndeavourOS/Manjaro-class), x86_64 GA first. Arch ARM is a separately gated experiment.

**Architecture verdict — [PROPOSAL]:** keep the proven React/Vite presentation, host it in Tauri 2 using the distro WebKitGTK runtime, move privileged/application behavior into one in-process Rust desktop core, replace local PostgreSQL with a deliberately reimplemented SQLite repository, and preserve protocol/data compatibility at the logical layer. The normal application owns no system daemon and opens no listening socket. Packaging is Linux-native: a signed pacman package/repository/PKGBUILD path is primary; AppImage is a fallback distribution channel, not the architecture.

Secrets prefer a freedesktop Secret Service provider (GNOME Keyring/KWallet-compatible implementations as available). If none is usable, the application offers a passphrase-derived local vault or session-only mode; plaintext fallback is forbidden.

This blueprint is intentionally not a Windows document with names replaced. Arch-specific constraints—rolling ABI, system WebKitGTK, XDG, Wayland/X11, D-Bus/portals, keyring absence, pacman ownership, package-managed updates, partial-upgrade prohibition and optional systemd user services—drive materially different decisions.

## Evidence notation

- **[FACT]** directly observed in uploaded sources or an official platform/specification source.
- **[INFERENCE]** conclusion from facts; plausible but must remain revisable.
- **[PROPOSAL]** chosen target design.
- **[EXPERIMENT-NEEDED]** requires empirical validation before the associated promise can be GA.

## Reading order

1. `00-executive-architecture.md`
2. `01-current-state-reconstruction.md`
3. `02-requirements-options-adr.md`
4. `03-components-data-storage-sync-security.md`
5. `04-arch-integration-packaging-update.md`
6. `05-release-diagnostics-performance-risk.md`
7. `06-compatibility-migration.md`
8. `07-roadmap-devctl-tests-experiments-do-not.md`
9. `19-adr/*`
10. `20-sources-and-evidence.md`
11. `MANIFEST.sha256` — SHA-256 integrity manifest for the documentation set

## One-line implementation target

> A standard user installs a normal Arch package, launches p2pKanban under Wayland or X11 without Docker/PostgreSQL/Node, works offline from a durable SQLite profile, keeps secrets out of plaintext, synchronizes through the existing versioned protocols, survives rolling-system changes and suspend/network switches, and can migrate/recover/update without giving the application ownership of system package state.

## Scope boundary

This package is a blueprint for implementation through devctl/AI patches. It is not code, does not claim unmeasured performance, and does not promote currently experimental Iroh/coordinator paths to production merely because desktop makes them possible.
