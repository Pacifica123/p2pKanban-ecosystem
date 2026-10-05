# A11 — device-link/2 + web-node-link / portable import migration

## Scope

A11 implements the native **destination/import boundary** for the compatibility
contracts frozen in A00. It does not reimplement the web deployment or turn the
Tauri WebView into a privileged migration agent.

Implemented contracts:

- `p2p-kanban-device-link/2`, with stable grant/request/response kinds
  `27780/27781/27782`;
- portable bundle `p2p_planner_bundle`, format version `1`;
- web-node-link envelope `p2p-kanban-web-node-link`, version `1`, bounded to
  32 MiB;
- SQLite schema v5 for import receipts, native principal metadata, capability
  metadata and preserved opaque portable sections;
- `SecretVault`-only persistence for device private keys and board capability
  keys;
- empty/fresh-profile migration for device-link, web-node-link and portable bundle import;
- replay rejection by source digest and atomic SQLite graph import;
- portable bundle parse → canonical export → parse roundtrip for the A00 fixture, including exact preservation of a non-null card `archivedAt` value;
- explicit omission reporting for node-local/deployment state that is not
  portable.

## Portable vs local state

Portable state is application data and compatibility metadata: stable UUIDs,
owned workspace/board/planner content, capability epochs, tombstones when the
native link adapter supplies them, and forward-compatible entity/portable
sections. A11 treats the portable bundle path specifically as a **migration**
into an empty/fresh native profile. The fixture `restoreHints.recommendedStrategy`
is preserved as advisory opaque metadata; it is not interpreted as permission
to destructively overwrite or silently remap logical IDs. Keeping the stable
IDs is required for web/Android/native coexistence without forking board identity.

The following are **not** imported as native profile data:

- password hashes, active sessions and bearer/refresh tokens;
- Docker volumes/networks/image tags and PostgreSQL/SQLite database files;
- deployment JWT/global-master/Nostr-signing secrets;
- browser cookie/localStorage state;
- machine-local Secret Service/KWallet records;
- legacy server/browser device records or replica identity.

A native device/replica identity is fresh. Imported capability metadata must bind its subject to that native principal public key; a mismatched subject is rejected before persistence. Board/device secret bytes are never stored in SQLite and never cross the WebView IPC surface.

## Atomicity boundary

SQLite and Linux Secret Service cannot participate in one ACID transaction.
A11 therefore uses a fail-closed two-resource sequence:

1. validate the complete import graph and repository preflight;
2. reject collisions with already-existing vault keys;
3. write new device/board secrets to `SecretVault`;
4. apply planner/import metadata inside one `BEGIN IMMEDIATE` SQLite transaction;
5. on a subsequent vault/SQLite error, best-effort delete only the keys written
   by this attempt.

This ordering prevents a committed board from becoming active without its
required secret. A process crash between vault write and SQLite commit may leave
an unreachable orphan secret; it cannot leave a half-imported planner graph.
No pre-existing vault value is overwritten, so compensation cannot delete an
older valid secret.

Imported state is a restored/linked replica seed, not a fresh user mutation.
A11 therefore does **not** populate `pending_local_changes` during import.

## Web-node-link v1 omissions

The native destination records/reports that v1 does not migrate shared
workspaces or node-local hides, in addition to password/session/token/device and
deployment secret state. Destination provisioning is rejected unless the native
profile is empty.

## Dependency prerequisite corrections

The A10 UTS reached `cargo.lock.offline-recheck` and showed that the direct exact
`serde = 1.0.229` pin conflicted with the host's offline `serde 1.0.228` cache
line. Per the agreed patch sequence, A11 retains the direct compatibility pin at
**1.0.228**. There is no A10b/A09c stage.

The first A11 host UTS then exposed the systemic part of the same class of
failure: all deterministic/frontend checks passed, online lock generation
selected exact `serde_json 1.0.151`, but the immediate offline recheck could see
only the host's already-cached `serde_json 1.0.149` line for Tauri. The verifier
was attempting its locked `cargo fetch` only after that recheck. Online
`generate-lockfile` alone is not sufficient cache preparation.

A11 therefore does **not** chase the machine cache by lowering `serde_json`. When
network preparation is explicitly allowed, the canonical verifier now generates
the online lock, performs locked online `cargo fetch` for that exact graph,
removes the online-created lock, regenerates it with `--offline`, requires the
offline lock to be byte-identical, and only then proceeds to locked offline
fetch/test/build. The mandatory offline resolver gate is strengthened, not
skipped or relaxed.

## Security boundary

A11 adds no generic filesystem, shell, network or keyring capability to the
WebView. `main-minimal` remains permission-empty and CSP `connect-src` remains
`none`. `DeviceIdentityMaterial` and `BoardCapabilityMaterial` deliberately do
not derive `Debug`; their secret payloads use `SecretValue`.

## Explicit non-claims

A11 does not claim a live Nostr device-link relay coordinator, Nostr signature/
chunk verification adapter, or legacy web-node HTTP/session client. The service
methods consume data already authenticated/decrypted by a native transport
adapter and revalidate the stable protocol/scope/expiry/destination semantics
before persistence. No boolean `trusted=true` or equivalent bypass is accepted.

A11 also does not claim A12 labels/comments/activity/appearance native UI
parity. Portable sections that are not yet first-class native entities are
preserved as validated opaque JSON so migration does not silently discard them.

## Verification

Deterministic `tools/check_a11.py` verifies schema/dependency/security/contract
invariants, source anchors, UTS strictness and SSOT evidence. The canonical
`tools/uts_verify.py` now runs A00→A11 twice and adds the host Cargo probe
`a11-import-compatibility` (`cargo test ... a11_ -- --nocapture`).

The construction environment has no Cargo toolchain, so Cargo compilation,
resolver and host Secret Service evidence remain delegated to the user's UTS.
The cache-order correction was proven far enough by UTS `20260915T073257Z` to
reach real offline Rust compilation. That run exposed source-only compile defects:
ambiguous `serde_json::Map::entry("...".into())` calls and a stale A09
`VaultStatus` test initializer. Both are corrected inside A11, with deterministic
guards added; another UTS rerun is required for final Cargo/build/runtime
acceptance.
