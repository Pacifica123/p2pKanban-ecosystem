# A04 — repository semantic contract suite

**Status: implemented at storage-independent contract/reference-adapter level.** No SQLite or PostgreSQL runtime dependency is introduced by this stage.

## Fact

The supplied web/backend and Android snapshots establish semantics that are stronger than any SQL dialect:

- cards have stable identity and numeric order keys;
- deterministic card ordering uses `position` and a stable ID tie-break where clients render equal positions;
- archive is reversible state, while delete removes the live card and creates/retains a tombstone;
- the legacy web delete path performs live-row deletion state + tombstone + audit/activity in one database transaction;
- column reorder validates that every requested card belongs to the target column before committing the batch;
- workspace-scoped sync writes require the submitted access epoch to exactly equal the current workspace epoch;
- Android roaming compares version stamps by `logicalClock`, then `replicaId`, then `eventId`, and a card tombstone prevents later `card.put` resurrection;
- relay acknowledgement is transport evidence only, not proof that a logical mutation has reached the coordinator projection.

The exact source hashes used for this extraction are frozen in `evidence/a04-repository-semantics.json`.

## Inference

The durable desktop boundary should expose atomic semantic commits and domain values, not `sqlx::Transaction`, PostgreSQL operators, SQLite connection handles, or a generic SQL abstraction. This allows the SQLite adapter to preserve behavior without pretending that SQL syntax is portable.

A tombstoned card ID is therefore rejected by ordinary `CreateCard`. If a future product requirement introduces explicit resurrection/restore of globally deleted cards, it needs a distinct protocol/domain decision rather than an accidental adapter behavior.

## Proposal implemented by A04

A04 adds:

- `domain::planner` value types for workspace/board/column/card identity, access epochs, finite order keys, archive lifecycle, tombstones and roaming-compatible version ordering;
- `application::repository::PlannerRepository`, with read methods and an atomic `PlannerTransaction` mutation boundary;
- a pure in-memory reference adapter used only by Rust tests;
- an adapter-independent scenario function that A05's pre-seeded SQLite adapter must invoke as part of its own tests;
- executable scenarios for create/read, deterministic ordering, move, archive/unarchive, delete+tombstone, stale-epoch rejection, reorder scope validation and all-or-nothing batch failure.

No repository code imports Tauri, SQLx, SQLite, filesystem, network, process, Docker or HTTP types.

## Unresolved experiment / deliberately unfrozen semantics

1. **Position allocation gap:** legacy web uses `POSITION_GAP = 1024.0`; Android optimistic local-first uses `+1000`. A04 freezes only finite numeric order + stable ID tie-break. It does not canonize either allocation gap.
2. **Field-level merge ownership:** A04 does not turn a whole card into a last-write-wins record. Field-version/tombstone merge remains A10 sync-core work, with existing roaming vectors as the oracle.
3. **PostgreSQL execution:** this native repository does not add SQLx/PostgreSQL merely to claim a dual-adapter test. Legacy PG source is evidence. A05 must make SQLite run this same logical suite; a legacy PG extraction harness can be maintained with the web/backend line without contaminating the native runtime.
4. **ID creation policy:** supplied systems use UUID identities, but A04 value types only enforce non-empty opaque IDs so import/protocol evolution is not accidentally narrowed. Validation/generation policy belongs at the relevant application/import boundary.

## Exit / next stage

A04 is complete when `cargo test` executes the contract suite and the deterministic A04 gate confirms there is no storage/platform leakage. The next stage is **A05 — SQLite profile schema + atomic migration engine**, which must implement this contract rather than bypass it.
