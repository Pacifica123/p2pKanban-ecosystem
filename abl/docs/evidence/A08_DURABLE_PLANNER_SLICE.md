# A08 durable planner slice evidence

## Classification

### FACT

- A04 already defines storage-independent card CRUD/order/archive/delete+tombstone, access-epoch and atomic transaction semantics.
- The supplied legacy web migration stores checklist/checklist-item identity, numeric position, completion state and tombstone-compatible deleted state; its anchor SHA-256 is `14005dad14f613dcea448b77deb49024d968f23c0d601642455d8357d57e75d4`.
- The supplied Android client models checklist/item local-first operations, tombstone-aware merge and local append positions; its model anchor SHA-256 is `3ff0129f6430e2909881e2f71e1efe4021f21d7881f96ffff614ab459e869f40`.
- Web and Android position allocation are not identical (legacy web uses a 1024-style gap in observed code paths, Android uses 1000). Therefore the allocation step is not a cross-client/domain compatibility invariant.
- A07/A07b UTS is green on the user host and already proves workspace/board durability, Cargo build/test and native runtime launch.

### INFERENCE

- A08 can make the offline planner useful without implementing network convergence by persisting local mutations and a payload-free pending marker in the same SQLite transaction.
- A local append step can be an application policy as long as stable ordering remains `position` then stable ID and A10 owns protocol reconciliation.

### PROPOSAL IMPLEMENTED BY A08

- Schema v3 adds durable column metadata, checklists/items, checklist/item tombstones, local logical-clock state and payload-free `pending_local_changes`. Reader/writer floor becomes v3; older binaries must not write it.
- The application-facing `PlannerService` owns title validation, ID allocation and local position allocation. It depends on repository traits only; it does not import Tauri, SQLite, filesystem, process or network APIs.
- Card mutations reuse the A04 `PlannerRepository`; checklist/column operations use the adjacent `PlannerFeatureRepository`. Both implementations are SQLite infrastructure details.
- Every local planner mutation and its pending marker commit in one `BEGIN IMMEDIATE` transaction. The pending table stores only mutation kind/entity identity and sequencing metadata, not secret material or sync payloads.
- WebView access remains explicit allowlisted Tauri commands. No arbitrary SQL/filesystem/network/vault command is introduced.

### UNRESOLVED / NOT CLAIMED

- `pending_local_changes` is not an A10 sync outbox protocol and does not mean remote convergence. Payload/vector/field merge semantics remain A10.
- Descendant checklist tombstone behavior across remote card deletion/replay is a sync-core merge question; A08 only proves local stale-ID resurrection blocking for explicit checklist/item deletion.
- Production Secret Service/KWallet/passphrase-backed secret persistence remains A09.
- Exact cross-client position allocation/rebalancing remains compatibility work; A08 intentionally does not elevate `1000` to a domain/wire constant.

## Acceptance

Deterministic acceptance is `python3 -B tools/check_a08.py`. Canonical UTS additionally runs the full Cargo suite and a filtered `a08_` durability/tombstone/forced-abort probe. Manual UI evidence is limited to the visible planner workflow and does not upgrade pending-local state to sync evidence.
