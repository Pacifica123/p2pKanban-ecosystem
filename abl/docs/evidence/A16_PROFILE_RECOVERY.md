# A16 — verified backup / doctor / safe-mode / recovery

## Status

Implemented at source and deterministic-contract level. Canonical Cargo compilation and real-binary A16 host recovery evidence are pending the next UserTestSpace run; this document does not claim those host results before they exist.

## Implemented boundary

A16 introduces a storage-independent recovery application service plus a Linux/SQLite adapter. The domain/application layers name profile backup/recovery concepts without importing SQLite, Tauri, filesystem or Linux primitives. Infrastructure owns SQLite read-only validation, connection-level snapshots, manifests, private-file handling and restore mechanics.

Normal startup now performs doctor/preflight after profile ownership is acquired but before the first writable repository open. Healthy old-schema profiles receive a verified A16 snapshot before migration. Unsafe/corrupt/incompatible/interrupted profiles fail into explicit recovery guidance instead of repeatedly attempting normal startup.

The CLI/native recovery plane provides doctor, manual backup, verified restore-point listing, safe-mode summary, logical salvage export and confirmation-gated restore. It takes the same kernel `flock` resource as normal ownership but deliberately creates no activation socket and constructs no WebView/network service.

## Safety properties encoded in source/tests

- live snapshots use rusqlite/SQLite Online Backup API, not `cp profile.db`;
- manifests bind SHA-256, size, schema/app version, integrity/FK result and selected counts;
- preflight validates the exact migration-ledger prefix and `profile_meta` version for both current and older supported schemas before permitting migration;
- restore points reject symlinks/non-regular files, manifest/hash/count/schema drift and future incompatible schemas;
- doctor is read-only and treats dangling/symlink DB paths as recovery failures rather than fresh profiles;
- sensitive vault/wrapper/journal files are checked for regular-file/private-permission shape;
- restore requires explicit CLI confirmation, creates a healthy pre-restore point when possible, quarantines current DB/WAL/SHM/journal and post-verifies the installed snapshot; quarantine preparation rolls already-moved files back if directory durability sync fails;
- safe logical export is `O_NOFOLLOW`, private-mode and excludes operational/session/capability state;
- safe-mode/recovery is available before WebView creation and does not start A14 LAN compatibility transport.

## Canonical A16 host evidence contract

`tools/a16_host_recovery_probe.py` uses an isolated XDG tree and the built debug binary. It constructs a valid current profile from checked-in migrations/checksum constants, then proves:

1. healthy doctor reports schema 6 without safe mode;
2. manual backup returns a manifest and verifies in restore-point listing;
3. a persisted mutation remains unchanged when restore is attempted without `--yes`;
4. confirmed restore recovers the pre-mutation content and passes post-restore integrity;
5. a verified `pre-restore-*` point preserves the replaced healthy state;
6. safe logical export contains recovered planner content while omitting sync operational state;
7. a corrupt profile forces safe mode without being mutated;
8. recovery does not bind the normal graphical activation socket.

This real-binary probe, plus `cargo test ... a16_`, remains **pending** in the patch-construction environment because Cargo/Rust are not installed there.

## Non-claims

A16 does not add a public backup/interchange protocol, SQLCipher, arbitrary damaged-SQLite salvage, WebView recovery UI, package-manager privileges, self-update/runtime downloads, relay/Iroh recovery or a new schema. `p2pkanban-recovery-logical` is a salvage artifact, not A11 `p2p_planner_bundle`.
