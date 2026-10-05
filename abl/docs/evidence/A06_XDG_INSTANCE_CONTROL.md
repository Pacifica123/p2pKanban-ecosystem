# A06 — XDG filesystem adapters + profile instance control

**Status: implemented at source/test level; Cargo/runtime host evidence is delegated to canonical UserTestSpace verification.**

## Fact

- The architecture baseline assigns mutable data to XDG data/config/state/cache roots and permits runtime sockets/locks only as ephemeral user-session state.
- A05/A05b are UTS-green and provide the durable SQLite profile/migration layer behind `PlannerRepository`.
- Linux sessions cannot be assumed to provide systemd-user, a tray host, Secret Service, NetworkManager, or even `$XDG_RUNTIME_DIR`.
- SQLite locking alone does not coordinate future process-level migration/sync/import lifecycle ownership.

## Inference

A kernel-owned advisory lock is safer than a PID lock file because process death releases it automatically. Locking the already-owned profile directory inode creates no persistent runtime lock artifact. A Unix-domain activation socket is useful only when a secure XDG runtime directory exists, so routing is a capability layered on top of writer exclusion rather than a prerequisite for correctness.

## Proposal implemented by A06

- resolve `$XDG_DATA_HOME`, `$XDG_CONFIG_HOME`, `$XDG_STATE_HOME`, `$XDG_CACHE_HOME` using XDG defaults from `HOME`; relative XDG values are ignored as required by the XDG model;
- create `p2pkanban/profiles/default/profile.db`, `backups/`, config/state/cache subtrees as user-owned application data, never under `/usr`;
- move migration backup/journal from A05 temporary DB sidecars into `profiles/default/backups/pre-migration-vN.sqlite` and `profiles/default/migration-journal.json`;
- enforce 0600 on the profile database, migration backup and journal created by this layer; app-owned directories are created 0700;
- acquire `flock(LOCK_EX|LOCK_NB)` on the profile directory before Tauri startup; SQLite WAL locking remains defense-in-depth;
- when a secure runtime directory exists, bind mode-0600 `$XDG_RUNTIME_DIR/p2pkanban/instances/default.sock` and route only the fixed `activate-main-v1` datagram;
- when runtime IPC is unavailable, retain single-writer correctness and degrade only window-activation routing (`SecondaryInstance::RoutingUnavailable`);
- expose a non-privileged diagnostics snapshot containing resolved roots/profile DB location plus whether runtime activation is available;
- package uninstall semantics remain: `/usr` package files are package-owned, while XDG data/config/state and future vault data are user-preserved unless explicitly purged by the user.

## Security / correctness boundary

The WebView receives no filesystem API from A06. XDG resolution and locking are Rust infrastructure concerns. Profile names are path-component validated. Runtime IPC accepts no arbitrary file/URL/shell payload. No network listener, root transition, system service, firewall mutation or keyring assumption is added.

## Tests

Rust tests cover explicit/default/relative XDG paths, invalid profile traversal, missing/unsafe runtime directories, non-root unwritable persistent roots, second-instance routing, no-runtime second-writer rejection, stale socket recovery, guard reopen and abnormal child-process exit. Existing SQLite contract/reopen/migration tests run after the recovery-layout refactor.

`tools/a06_host_instance_probe.py` additionally launches the real built binary twice in isolated XDG directories and verifies routed second-instance exit, primary survival, restart after primary termination, and missing-runtime degraded behavior.

## Unresolved / later stages

- Filesystem qualification beyond normal local XDG storage (NFS/SMB/FUSE/cloud-sync) remains A18 experiment/hardening; A06 does not claim those live-profile locations are supported.
- Rich deep-link/file-open intent routing remains A13/A14 and must add validation before expanding the fixed activation protocol.
- Secret Service/KWallet/passphrase fallback remains A09.
- Recovery backup retention/manifest UX remains A16; A06 only places migration artifacts into the final profile recovery directory.

The exact next architecture patch is **A07 — minimal durable auth/workspace/board slice + vault interface**.
