# A05b — UTS rusqlite backup API compile correction

## Fact

The first A05 UserTestSpace run on Manjaro resolved and cached `rusqlite 0.40.2`, then failed both `cargo test --locked --offline` and `cargo build --locked --offline` at `migration.rs`: `rusqlite::DatabaseName` is not exported by this version. The same run had already passed all deterministic, frontend, and host-doctor gates; the native runtime probe was blocked only because the Rust binary was not produced.

For `rusqlite 0.40.2`, `Connection::backup` and `Connection::restore` accept a database name through the generic `Name` API. The primary database is therefore passed as the literal `"main"`. No schema or migration semantics change in A05b.

## Inference

This was an API-shape compile defect in the A05 adapter, not evidence against the SQLite architecture, bundled SQLite choice, migration backup policy, or UTS host prerequisites.

## Correction

- remove the obsolete `DatabaseName` import;
- use `conn.backup("main", ...)` and `conn.restore("main", ...)`;
- keep the forced migration failure/restore test as the runtime authority for the recovery path;
- remove unused `pub use` re-exports while keeping SQLite modules crate-visible;
- make the A05 deterministic regression gate forward-compatible with later UTS stages;
- add a dedicated A05b guard so the obsolete API cannot silently return.

## Verification

Deterministic checks do not claim Rust compilation. In UTS, `python3 -B tools/uts_verify.py` must produce PASS for `cargo.test` and `cargo.build`; only then is A05b host-verified. If dependency caches are incomplete, `--allow-network` may be used once for preparation and the verifier will still recheck acceptance offline.

## Proposal / next stage

A05b is a compile correction only. A06 subsequently owns XDG layout and instance control without changing the corrected rusqlite API.

## Unresolved

Dedicated rendered-WebView hostile-navigation evidence remains outside this SQLite correction and stays tracked separately.
