# 20 — Sources and evidence inventory: Arch Linux blueprint

> **A00 provenance correction (2026-09-12):** the attached archive copies use suffixes `(3)` / `(2)` instead of the `(1)` names recorded during the architecture pass. Their SHA-256 digests are identical to the reviewed logical snapshots, so this is a filename/provenance normalization only; no architecture decision is superseded.


## Uploaded archives reviewed

All entries of the three supplied archives were enumerated before selecting high-value implementation evidence.

| Archive | Files | SHA-256 | Main evidence |
|---|---:|---|---|
| `post_kanban_20260911_215622_after_workspace-sync_c36ad4c(3).zip` | 543 | `8b7346397b6135b4f2b7c27f59d32f522ea9eb5b34e3b22530606f1302ce9ce6` | web/backend v2, deployment, migrations, sync, import/export, coordinator experiments |
| `post_kanban_android_20260912_143315_after_workspace-sync_65fea82(3).zip` | 137 | `c463f8fd5a99c1a5214e2ed98044875ba74b78aa0023b0e011eefb205685de5d` | Android local-first, secure session storage, roaming merge, device-link |
| `devctl(2).zip` | 10 | `c4876b3bd55f8fd996f248d9c18e78c961471e502c6ac578c1c124105c06c9af` | devctl v0.7.0 patch/workspace pipeline |

## High-value project evidence

### Web/backend
`README.md`; `VERSION`; `backend/Cargo.toml`; `backend/src/main.rs`; `backend/src/config.rs`; `backend/src/auth/*`; `backend/src/modules/sync/*`; `backend/src/modules/integrations/*`; `backend/crates/sync-core/src/*`; `backend/crates/nostr-transport/src/lib.rs`; `backend/crates/iroh-transport/src/lib.rs`; `backend/migrations/0001..0019`; `deploy/bootstrap/*`; `deploy/release/*`; `docs/adr/*`; `docs/architecture/import-export-backup-v1.md`; `docs/architecture/web-node-link-v1.md`; `docs/architecture/auth-and-identity-v1.md`; `docs/architecture/local-first-data-layer-v1.md`; `docs/architecture/security-privacy-threat-model-v1.1.md`; `docs/sync/roaming-board-protocol-v1.md`; `docs/deployment/application-update-strategy-v1.md`; `docs/deployment/postgresql-backup-restore-v1.md`; `frontend/src/shared/api/client.ts`; `frontend/src/features/localFirst/*`; `frontend/src/features/sync/*`; `edge-coordinator/*`.

### Android
`README.md`; `package.json`; `src/shared/storage/storage.ts`; `src/shared/api/endpoints.ts`; `src/features/auth/AuthProvider.tsx`; `src/features/localFirst/model.ts`; `repository.ts`; `snapshot.ts`; `src/features/roaming/types.ts`; `codec.ts`; `merge.ts`; `service.ts`; `storage.ts`; `src/features/deviceLink/protocol.ts`; `service.ts`.

### devctl
`README.md`; `devctl.py`; `docs/devctl-universal-v0.3-README.md`; `docs/patch-intake.md`; `docs/patch-manifest.example.json`; `docs/release-cli.md`; `.devctl/workspace.json`.

## Arch/Linux primary references

Validated against current public documentation during the architecture pass (September 2026):

- Tauri v2 process model — https://v2.tauri.app/concept/process-model/
- Tauri v2 prerequisites / Arch WebKitGTK dependencies — https://v2.tauri.app/start/prerequisites/
- Tauri v2 Linux distribution overview — https://v2.tauri.app/distribute/
- Tauri v2 AppImage — https://v2.tauri.app/distribute/appimage/
- Arch system maintenance / unsupported partial upgrades — https://wiki.archlinux.org/title/System_maintenance
- Arch `makepkg` — https://wiki.archlinux.org/title/Makepkg
- Arch `PKGBUILD` — https://wiki.archlinux.org/title/PKGBUILD
- Arch clean-chroot/package build guidance — https://wiki.archlinux.org/title/DeveloperWiki:Building_in_a_clean_chroot
- Arch build system / AUR distinction — https://wiki.archlinux.org/title/Arch_Build_System
- XDG Base Directory Specification 0.8 — https://specifications.freedesktop.org/basedir/0.8/
- Secret Service API — https://specifications.freedesktop.org/secret-service/latest/
- Desktop Notifications Specification — https://specifications.freedesktop.org/notification/latest/
- StatusNotifierItem Specification — https://specifications.freedesktop.org/status-notifier-item/latest-single/
- XDG Desktop Portal FileChooser — https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.FileChooser.html
- SQLite WAL — https://www.sqlite.org/wal.html
- SQLite `PRAGMA synchronous` — https://sqlite.org/pragma.html
- SQLite Online Backup API — https://www.sqlite.org/backup.html

## Evidence policy

1. Executable code and migrations outrank roadmap/aspirational prose when they conflict.
2. Existing docs are evidence of intended contracts only where code/tests do not contradict them.
3. Android is treated as a semantic/local-first reference, not proof that Expo/AsyncStorage/SecureStore should become Linux desktop runtime architecture.
4. External sources establish Arch/XDG/WebKitGTK/package behavior; p2pKanban semantics come from the supplied archives.
5. Unknowns stay marked **[INFERENCE]** or **[EXPERIMENT-NEEDED]**.
6. Arch compatibility assumes a coherent system state; partial-upgrade states are explicitly outside the supported target rather than “fixed” with private copied libraries or signature bypasses.
