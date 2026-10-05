# ADR-002 — Arch local storage

**Status:** proposed  
**Decision:** one SQLite DB per desktop profile, WAL + foreign keys + `synchronous=FULL` initially, with a dedicated desktop schema/migration line behind domain/repository interfaces.

## Grounds
- [FACT] Existing backend SQL is deeply PostgreSQL-specific (`jsonb`, PG casts/operators, helpers, `SKIP LOCKED`, timestamptz/interval semantics).
- [FACT] Native desktop objective excludes a local PostgreSQL daemon/runtime.
- [INFERENCE] Explicit semantic reimplementation behind repository contracts is safer than pretending SQL dialects are interchangeable.
- [PROPOSAL] Serialized local writer + durable outbox matches the single-user desktop workload while protocol merge handles replica concurrency.

## Rejected alternatives
- Bundled PostgreSQL: service/update/backup/admin footprint contradicts target UX.
- JSON/AsyncStorage authority: weak relational/integrity/query/transaction properties for full desktop feature set.
- Generic PG-compatible embedded engine: extra maturity/supply-chain risk without proof it preserves all relevant semantics.
- Raw DB file interoperability: couples clients to implementation storage and secrets.

## Costs
New schema, migrations, query implementations, repository-contract suite and legacy migration adapter.

## Failure modes
Semantic drift from PG behavior; DB on unsupported NFS/FUSE/cloud filesystem; WAL growth; old app writes newer schema; disk-full migration failure.

## Verification
Run shared logical contract suite against PostgreSQL + SQLite; crash/power/suspend fault injection; `foreign_key_check`/`integrity_check`; migration backup/restore; filesystem matrix; min-reader/min-writer downgrade gates.
