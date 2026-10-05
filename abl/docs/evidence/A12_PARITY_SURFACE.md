# A12 — labels/comments/activity/appearance parity

## Scope

A12 materializes the remaining planner-adjacent parity surface that A11 preserved
losslessly but did not expose as first-class native data: labels/card-label edges,
comments, activity provenance, and board appearance.

The stage is deliberately split by proven wire capability rather than pretending
all four feature groups have identical sync support:

- labels and comments are durable native entities with typed application/SQLite/IPC/UI contracts;
- every local label/comment mutation is recorded in `parity_local_changes` with
  reason `roaming-v1-unsupported` because the frozen `p2p-kanban-roaming/1`
  operation set contains no compatible label/comment mutation;
- activity is provenance. A12 records native parity mutations atomically with the
  mutation and preserves imported activity, but never fabricates legacy history;
- appearance uses the already-established `board.appearance.put` operation and
  snapshot `appearance` section, so it participates in the existing A10 pending →
  outbox/merge path rather than the unsupported parity ledger.

## Storage and application boundary

Schema v6 adds `labels`, `card_labels`, `comments`,
`board_appearance_settings`, `activity_entries`, and `parity_local_changes`.
Local label/comment mutation + unsupported-sync marker + activity entry are
committed in one `BEGIN IMMEDIATE` transaction. Appearance update + normal A10
pending marker + activity entry are likewise atomic.

`activity_entries.card_id` is intentionally provenance text rather than a
cascading FK. Deleting a card/comment/label must not rewrite history by deleting
an activity row that records what happened.

The new `domain::parity` and `application::parity` layers contain no rusqlite,
Tauri, Secret Service, filesystem, or network dependency. The WebView receives
only bounded typed parity commands; `main-minimal` stays permission-empty and CSP
continues to disable WebView network access.

## A11 import materialization

A11 already preserved portable sections `labels`, `cardLabels`, `comments`,
`boardAppearanceSettings`, and `activityEntries` as opaque JSON. A12 now
materializes those sections into schema v6 during the same fresh-profile import
transaction while retaining the opaque copy for lossless export compatibility.
Imported seed data creates neither `pending_local_changes` nor
`parity_local_changes`: migration is not a local user mutation.

`fixtures/export/portable-board-bundle-v1-parity.json` is an A12 synthetic
regression fixture derived from the A00 portable shape. It exercises all five
parity sections but is not claimed to be a newly discovered exact legacy JSON
fixture; the importer therefore accepts a bounded set of already-observed naming
aliases and preserves each raw object.

## Roaming compatibility

A00/A10 evidence proves `board.snapshot` includes `snapshot.appearance`, cards
carry `labelIds`, and the accepted operation family contains
`board.appearance.put`. It does **not** prove label/comment mutation operations.
A12 therefore refuses to invent `label.put`, `comment.put`, or similar protocol
extensions.

For local appearance writes A12 emits the proven operation name with normalized
`payload.appearance`. This mapping is an Arch-native normalized representation
covered by Rust roundtrip/apply tests; without the original source archive in this
construction environment, A12 does not claim byte-for-byte identity with an
unseen Android appearance event body.

## UI parity

The desktop surface now exposes:

- board label create/delete and card label assignment;
- card comments create/list/delete;
- editable board appearance JSON, normalized to the opened `boardId`;
- recent activity provenance;
- separate counters for roaming-capable A10 pending changes and
  roaming/1-unsupported parity mutations.

The user-visible wording keeps the compatibility gap explicit instead of
presenting local durability as remote convergence.

## Verification and non-claims

`tools/check_a12.py` verifies schema checksum/versioning, architecture boundaries,
unsupported-operation honesty, A11 import materialization, typed IPC/UI wiring,
source anchors, UTS registration, and evidence hashes. Canonical UTS adds the
`a12_` Rust test probe after normal offline Cargo test/build.

A12 does not add live relay orchestration, a new roaming protocol version,
attachments, desktop lifecycle/tray/notification integration, or generic
filesystem/keyring privilege. Those remain later stages. A13 is the next
architecture stage after A12 receives a green canonical UTS.

## A12 host compile correction

`CORR-A12-001` records the first canonical host Cargo result: deterministic/frontend/offline dependency acceptance passed, while Rust rejected the portable parity `section_array()` helper with `E0515` because it returned references into function-local parsed JSON. The helper now returns owned object maps; this is a compile-correctness correction only and does not change schema, import semantics, IPC privilege or roaming claims.
