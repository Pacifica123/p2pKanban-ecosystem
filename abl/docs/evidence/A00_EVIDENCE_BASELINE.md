# A00 evidence baseline

Status: **implemented**  
Patch boundary: **A00 only**  
Runtime feature claim: **none**

## Frozen facts

1. The supplied web/backend snapshot is p2pKanban `2.0.0` and its normal user path is browser + Docker Compose + Rust/Axum + PostgreSQL. This is legacy/current-product evidence, not the desktop runtime target.
2. `p2p-kanban-sync/1` is defined by the Rust `sync-core` crate and has transport-neutral event/envelope structures.
3. `p2p-kanban-roaming/1` is implemented across backend/Android semantics; card lifecycle tombstones and capability epochs are correctness constraints for later desktop compatibility.
4. Android uses a local-first device model and separates secure session material from ordinary AsyncStorage. Android storage technology itself is **not** a Linux architecture choice.
5. Device linking uses `p2p-kanban-device-link/2` with signed Nostr events, bounded delegation chains and bounded encrypted snapshot payloads.
6. Portable application export uses logical format `p2p_planner_bundle`, `formatVersion = 1`; raw PostgreSQL/SQLite dumps are not a public interchange format.
7. The legacy backend has migrations `0001` through `0019`. Their digest is frozen in `evidence/migrations.sha256` for semantic archaeology only. A05 must not mechanically translate them to SQLite.
8. The supplied devctl is v0.7.0 and requires `formatVersion: 1`, safe relative payload paths, deterministic declared checks and commit-after-green behavior with rollback/archive on failure.

## Architecture conclusions carried forward

- **proposal:** Tauri 2 + distro WebKitGTK + in-process Rust core.
- **proposal:** typed Tauri IPC is the desktop frontend boundary; no arbitrary WebView filesystem/process/network privilege.
- **proposal:** SQLite behind repository contracts, introduced only after A03/A04.
- **proposal:** XDG-compliant per-user profile/config/state/cache; normal use has no root requirement.
- **proposal:** pacman/PKGBUILD is primary packaging; AppImage is a separately validated fallback.
- **proposal:** Secret Service is a capability, not an assumption; plaintext secret fallback is forbidden.
- **experiment-needed:** exact rolling-release WebKitGTK/GTK/glibc support floor, AppImage behavior, tray/notification/keyring matrices, Arch ARM, performance/power budgets.

## Drift decision

The architecture package referenced archive copies named `(1)`, while this implementation input supplied `(3)` for web/Android and `(2)` for devctl. Their SHA-256 digests match the architecture-recorded digests exactly. Therefore A00 records a provenance-name correction only; no ADR is superseded.

## Why A00 does not create a fake native MVP

A01 is the first shell/runtime patch. SQLite would require A03 application separation and A04 repository contracts before A05; durable auth/board state is A07. Combining these into A00 would destroy the planned rollback boundaries and encourage PostgreSQL semantics to leak into desktop persistence. A00 therefore delivers the permanent evidence/SSOT foundation and nothing falsely labeled as runnable native functionality.

## Delivery-tool correction discovered during A00

A real devctl v0.7.0 application test exposed `DEBT-A00-001`: failed-patch auto-reset uses `HEAD`, so a commitless repository cannot be rolled back after partial apply. The supported first-patch path therefore uses a dedicated repository with an existing seed commit on `main` containing the `ARCH_NATIVE_REPO` identity sentinel. This is recorded in the living architecture debt ledger rather than hidden as an unstated bootstrap assumption.
