# A16 recovery procedure

A16 is the native profile-recovery layer for the Arch client. It operates before WebView startup and does not require relay/P2P/LAN connectivity.

## Normal startup preflight

After the existing profile flock is acquired, startup runs a read-only doctor before any SQLite repository is opened writable.

- A fresh profile is allowed to continue.
- A current schema-v6 profile must pass SQLite integrity, foreign-key, exact migration-line and schema metadata checks.
- An older supported profile must also match the exact migration-ledger prefix and `profile_meta` version for its `user_version`; only then does it get a **verified A16 pre-migration snapshot** through the SQLite Online Backup API before the existing migration engine opens it writable.
- A future/incompatible schema, corrupt DB, invalid migration journal, unsafe DB/sensitive-file path or inconsistent schema metadata blocks normal startup and points to safe mode.

This preflight never treats a later WebKit/WebView launch failure as proof that the database is corrupt.

## CLI recovery commands

Run these with the normal GUI process closed so the recovery command can own the same profile flock:

```bash
p2pkanban doctor
p2pkanban doctor --json
p2pkanban backup
p2pkanban backups
p2pkanban safe-mode
p2pkanban safe-export /path/to/recovery.json
p2pkanban restore <backup-id> --yes
```

`safe-export` refuses to overwrite an existing destination by default. Use `--force` only after checking the destination. `--json` is available for machine-readable reports.

Recovery commands do not bind the graphical activation socket and do not construct the Tauri WebView. They do not start A14 LAN compatibility, relay/Iroh sync, automatic update work, package-manager commands or schema migration.

## Verified profile backups

Manual, pre-migration and pre-restore recovery points are connection-level snapshots, never a raw copy of a live WAL database. Every A16 restore point has a JSON manifest binding:

- backup format/version and stable backup id;
- application and schema version;
- creation time and reason;
- SHA-256 and byte size;
- `PRAGMA integrity_check` + foreign-key result;
- selected workspace/board/card/pending/outbox row counts.

`backups` re-verifies the file type, size, SHA-256, manifest, SQLite integrity, schema compatibility and recorded counts. A tampered point is listed as unverified and cannot be restored.

The legacy A05 migration-local rollback file remains private migration machinery. A16 does not rewrite that proven engine; instead it creates its own verified restore point before an old-schema normal startup can migrate.

## Confirmed restore

Restore is destructive and therefore requires `--yes`.

Before replacement A16:

1. verifies the selected restore point;
2. materializes and re-verifies a private temporary copy;
3. when the current profile is healthy, creates a verified `pre-restore-*` snapshot;
4. quarantines the current `profile.db`, WAL/SHM and migration journal under the profile backup directory;
5. atomically installs the verified snapshot;
6. enforces private permissions and rechecks integrity/hash.

If quarantine preparation itself cannot be durably synced, A16 rolls already-moved profile files back before returning the error. If installation/post-verification later fails, A16 attempts to restore the quarantined state and keeps the selected immutable restore point untouched.

Restoring an older supported schema is allowed. The next normal startup will again create a verified pre-migration point before migrating it forward.

## Safe logical export

`safe-export` is deliberately a recovery/salvage artifact named `p2pkanban-recovery-logical` v1. It exports readable planner content from a DB that passes read-only integrity checks. It omits operational/session/capability state such as sync outbox, pending markers, device principal/capability metadata and migration bookkeeping.

It is **not** the public A11 `p2p_planner_bundle` format and is not claimed to be directly importable. Use A11 portable export/import for normal cross-client interoperability; use A16 logical export when recovering readable planner content without relying on the WebView.

## Canonical acceptance

A16 deterministic checks are network-free. Canonical UserTestSpace additionally owns real Rust and binary evidence:

```bash
python3 -B tools/uts_verify.py --allow-network
```

A16-specific post-build evidence runs `cargo test ... a16_` and the real-binary `tools/a16_host_recovery_probe.py`. The host probe proves healthy doctor, verified manual backup, refusal of unconfirmed restore, successful confirmed restore, preservation of a pre-restore point, logical salvage export, corrupt-profile safe mode and absence of the graphical activation socket.
