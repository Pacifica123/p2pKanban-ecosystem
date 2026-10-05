# A05 — SQLite profile schema + atomic migration engine

**Status: implemented at adapter/schema/migration-test level; host Cargo evidence is delegated to canonical UserTestSpace verification.**

## Fact

- A04/A04b are green in UserTestSpace, so persistence can now implement the repository semantics instead of defining them.
- The architecture baseline selects one SQLite database per desktop profile, foreign keys, WAL where supported, `synchronous=FULL`, bounded busy handling, explicit min-reader/min-writer schema metadata, integrity checks, and migration backup/restore.
- Legacy web persistence is PostgreSQL-specific and is evidence only. A05 does not translate server migrations or SQL syntax.
- The A04 evidence shows ordering/tombstone/access-epoch semantics that the SQLite adapter must preserve.

## Inference

A file-backed SQLite adapter behind `PlannerRepository` is the smallest durable storage step that preserves the final architecture. Keeping the profile path as an injected `Path` prevents A05 from prematurely owning XDG layout or multi-instance policy.

Bundling SQLite through exact-pinned `rusqlite` avoids a second rolling-release runtime ABI dependency on the host SQLite library. This is a build-time dependency choice, not a network/runtime service dependency. Cargo source acquisition is allowed during explicit build preparation and remains cacheable/offline afterward.

## Proposal implemented by A05

- desktop schema line starts at schema `1`, with `profile_meta(schema_version,min_reader,min_writer)`, an ID+SHA-256 `schema_migrations` record, plus planner workspace/board/column/card/tombstone tables; domain `u64` access epochs/Lamport clocks use canonical decimal TEXT so SQLite signed INTEGER cannot narrow them;
- `PRAGMA foreign_keys=ON`, file-backed `journal_mode=WAL`, `synchronous=FULL`, and a 2500 ms busy timeout are configured before writable use;
- profiles advertising a writer schema newer than this binary are refused rather than guessed/downgraded;
- v0→v1 migration uses `BEGIN IMMEDIATE`, creates an online SQLite backup for an existing profile, writes a small non-secret migration journal, and runs `integrity_check` + `foreign_key_check` before activation;
- an injected forced-failure test proves the original v0 database is restored from the backup and the journal records `restored-after-failure`;
- the production SQLite repository executes the same generic A04 contract suite and has an explicit close/reopen durability test.

## Security/data boundary

No token, private key, board key or vault root column exists in this schema. SQLite is not being declared a plaintext secret store. Secret persistence remains A09 behind the vault abstraction. Raw SQLite remains an implementation artifact, not a public interchange format.

## Unresolved / experiment-needed

- WAL suitability on NFS/FUSE/cloud-backed paths remains an A06/A18 capability/filesystem experiment. A05 fails if WAL cannot be activated; it does not silently weaken durability semantics.
- `synchronous=FULL` remains the initial policy; performance evidence may later justify an ADR change, not an implicit switch to NORMAL.
- A06 supersedes the temporary A05 sidecar placement: migration backups now live under the profile `backups/` directory and the migration journal lives at the profile root. A16 still owns retention/manifest/doctor UX.
- whole-database encryption remains an open architecture question; A05 does not claim it.

## Verification

`python3 -B tools/uts_verify.py` must make `deterministic.a05`, `cargo.test`, and `cargo.build` green. The Rust tests are the authority for the actual SQLite API/compiler behavior because the patch-authoring environment may lack Cargo.

A06 now owns final XDG placement and instance lifecycle; this A05 document remains provenance for the migration semantics.
