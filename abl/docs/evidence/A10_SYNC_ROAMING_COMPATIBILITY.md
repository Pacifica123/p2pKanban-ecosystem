# A10 — sync-core + roaming compatibility

Status: **implemented at source/deterministic-check level; canonical UTS Cargo compatibility run required**.

A10 also carries the UTS-driven resolver correction for A09b: the direct `getrandom` pin is aligned from `0.4.3` to `0.4.2` so a fresh-host network preparation can be re-resolved offline without relaxing the acceptance gate.

## Facts

- Legacy web `sync-core` fixes `p2p-kanban-sync/1`, orders version stamps by `logicalClock → replicaId → eventId`, and accepts `create/update/move/complete/delete/restore/reorder/add/remove/archive/unarchive` rather than a generic `put` operation.
- Android roaming fixes `p2p-kanban-roaming/1`, derives board tags with HMAC-SHA256 over `p2p-kanban:board-tag:v1 || 0x00 || boardId`, encrypts event JSON with XChaCha20-Poly1305, sorts by the same version tuple, and treats card tombstones as non-resurrectable by later `card.put` events.
- A08 `pending_local_changes` intentionally contains mutation identity only. A10 materializes compatible rows into a separate durable `sync_outbox`; it does not reinterpret the pending table as a wire protocol.

## Implemented boundary

- `domain/sync.rs`: protocol DTOs, validation, version ordering, replay/tombstone merge model, board-tag derivation and Android-compatible XChaCha record codec.
- `application/sync.rs`: repository/service boundary plus typed board-capability secret helpers that use `SecretVault` only.
- `infrastructure/sqlite/sync.rs`: durable outbox, seen-event digest guard, field versions, opaque extension preservation, local-marker materialization and deterministic remote batch application.
- schema v4: `sync_outbox`, `sync_seen_events`, `sync_field_versions`, `sync_entity_extensions`; no token/key/vault columns.
- local remote-apply observes the maximum incoming Lamport clock before later local allocations.
- fresh/empty native boards can consume Android `board.snapshot`; an already populated board is not overwritten by a later snapshot, matching Android's seed-only snapshot behavior.

## Explicit corrections to A00 baseline

The A00 fixtures were evidence placeholders, not protocol authority. Source inspection proved two fixture details stale:

1. `sync-envelope-v1.json` used operation `put`; actual web sync-core validation rejects it. A10 changes the fixture to `update`.
2. `roaming-card-put-v1.json` placed card fields directly in `payload`; Android `service.ts` emits `payload.card`. A10 normalizes the fixture and adds `deletedAt` to the delete fixture.

These are SSOT corrections to fixtures, not protocol extensions.

## Compatibility safeguards

- Synthetic crypto vector reproduces the Android codec test with a fixed non-secret board key and nonce and an independently derived ciphertext.
- Same event ID + different canonical body is rejected atomically as replay conflict.
- capability epoch mismatch is rejected before mutation.
- local materialized versions are persisted before remote merge, so an older remote event cannot overwrite newer local state.
- local delete pending identity reuses its tombstone `VersionStamp`; future reorders generate one uniquely versioned `card.move` marker per affected card instead of the older aggregate marker.
- unsupported A08 markers such as post-snapshot `column.create` fail closed. Legacy `roaming/1` has no column-mutation operation, so A10 does not invent one.
- an in-process relay-disruption harness deliberately drops one event, then delivers the remaining events out of order with replay duplicates; the second SQLite replica converges idempotently without treating transport delivery as semantic ACK.

## Non-claims

- No Nostr relay publish/pull coordinator is implemented yet; relay ACK is not semantic convergence.
- No device-link/import path is added in A10; that is A11.
- Board appearance is accepted/version-negotiated but not yet mapped into the native parity surface; A12 owns appearance parity.
- The full GNOME/KWallet/minimal-session secret-provider matrix remains separate A09 evidence.
