# 06 — Compatibility, version negotiation and migration from current Docker deployment: Arch Linux

## 1. Compatibility principle

**[PROPOSAL]** Desktop compatibility is defined by logical identity, application data and versioned protocol contracts—not by sharing PostgreSQL/SQLite files, SQL queries, browser storage or container images.

Preserve where already stable:
- stable UUID identity for users/workspaces/boards/cards/checklists/etc.;
- owned-workspace logical content;
- board capabilities and capability epochs;
- tombstones/deletion semantics;
- deterministic merge/version ordering;
- `p2p-kanban-sync/1`;
- `p2p-kanban-roaming/1`;
- `p2p-kanban-device-link/2`;
- `p2p_planner_bundle` `formatVersion = 1`;
- web-node-link v1 semantics and its explicit limitations.

Do not preserve as cross-client contracts:
- raw PostgreSQL table/layout/sequence state;
- raw SQLite file format as a public interchange format;
- browser cookies/localStorage;
- Docker volumes/network names/image tags;
- backend JWT signing/global master/deployment Nostr secrets;
- machine-local paths or desktop-environment/keyring internals.

## 2. Web ↔ Android ↔ Arch desktop compatibility matrix

| Capability/data | Web/backend v2 | Android v2 | Arch desktop target | Compatibility rule |
|---|---|---|---|---|
| Stable entity UUIDs | yes | consumes same IDs | preserve | identical logical UUID identity |
| User identity | PostgreSQL-backed | native session | local profile + native auth | same logical user, new device/session |
| Owned workspaces | yes | provisioned/roaming subset | preserve/import | logical node-link/export |
| Shared workspaces | yes | capability dependent | runtime support; migration gap | existing node-link v1 omits; reinvite/new contract |
| Boards/columns/cards | yes | local snapshot + ops | full SQLite local authority | same logical entities/events |
| Labels | yes | partial/node-dependent | A12 first-class local parity | durable application contract; roaming/1 mutation gap is explicit |
| Comments | yes | partial/node-dependent | A12 first-class local parity | durable application contract; roaming/1 mutation gap is explicit |
| Checklists/items | yes | roaming delta support | preserve delta/tombstones | deterministic rules unchanged |
| Appearance | yes | roaming support | A12 durable + roaming mapping | existing board snapshot / `board.appearance.put` family |
| Local hides/reminders/preferences | local semantics | device-local | device-local | never promote automatically to global state |
| Tombstones | yes | yes | preserve | versioned identity + merge semantics |
| Activity/audit | yes | partial/echo guard | A12 local/imported provenance | explicit provenance; no fabricated history |
| Browser cookie/session | yes | no | no | never migrate |
| Native access token | endpoint exists | memory-only | remote-session memory only; none for local IPC | legacy/coordinator HTTP compatibility |
| Native refresh token | endpoint exists | SecureStore | vault only for remote sessions | rotate; never import browser token or gate local IPC |
| Board key/tag capability | yes | yes | vault-protected | preserve/provision logical secret |
| Capability epoch | yes | yes | yes | stale writer rejection unchanged |
| Sync protocol | `sync/1` | backend/transport consumer | reuse Rust contract | golden vectors |
| Roaming protocol | backend/relay | `roaming/1` | compatible implementation | ciphertext/event vectors |
| Device link | server+mobile | `device-link/2` | participate | strict version/signature/expiry |
| Portable bundle | v1 | not full parity | import/export v1 | application-level only |
| Web node link | v1 source/destination | not primary | consume legacy source | empty destination/profile initially |
| Raw PostgreSQL | internal | no | no | unsupported interchange |
| Raw SQLite | no | AsyncStorage | implementation private | not cross-client contract |
| Nostr roaming | implemented | implemented | preserve | relays configurable/untrusted |
| Iroh | experimental Rust crate | no | optional experiment | never GA dependency initially |
| Edge coordinator | auxiliary/experimental | no | optional | no mandatory daemon |
| Attachments/blobs | reserved/not mature | no full parity | first-GA non-goal | future explicit contract |

## 3. Schema and protocol version negotiation

### Local desktop DB — [PROPOSAL]

Metadata:
- `schema_version`;
- `minimum_reader_version`;
- `minimum_writer_version`;
- `migration_set_digest`;
- `created_by_build`;
- `last_migrated_by_build`;
- `last_verified_backup`.

Startup behavior:
1. core opens metadata in a minimal/read-only preflight before normal UI mutation paths;
2. unsupported newer schema → refuse writes, expose doctor/recovery/export guidance;
3. older supported schema → verified pre-migration backup, migrate, then validate DB + domain invariants;
4. migration is not considered successful until post-checks pass and journal is finalized;
5. package downgrade is allowed to write only if its reader/writer contract includes the current schema;
6. otherwise restore a matching pre-migration snapshot before old binary use.

A rolling distro does not relax this contract: system package version and application data schema are separate version dimensions.

### Network protocols — [PROPOSAL]

Every wire envelope keeps explicit protocol/version. Unsupported major version fails closed with diagnostics. Additive fields may be ignored only where the existing protocol contract explicitly permits forward compatibility.

Negotiation/evidence may include:
- protocol version;
- supported operation families;
- writer capability epoch;
- maximum payload/event size;
- optional transport support;
- schema/export format versions where relevant.

Transport availability never changes logical merge semantics.

## 4. Preferred migration: running Docker/web node → Arch desktop

**[FACT]** web-node-link v1 already transfers stable user UUID, owned workspaces, planner content, appearance/archive state, tombstones and board capability material while excluding password hash, active sessions/tokens, device records and deployment secrets.

**[PROPOSAL]** Use that logical source contract as the primary same-user migration path into a new/empty Arch profile. The Rust desktop core—not WebKit JavaScript—talks to the source node and writes a staged SQLite destination.

```mermaid
sequenceDiagram
  participant U as User
  participant A as Arch desktop core
  participant L as Legacy Axum/Docker node
  participant S as Staged SQLite profile
  participant V as Secret vault provider

  U->>A: Migrate existing node
  A->>L: authenticate / request versioned node-link transfer
  L-->>A: logical transfer payload
  A->>A: validate version, size, IDs, references, capabilities
  A->>S: atomic staged import
  A->>S: FK/count/tombstone/epoch/domain checks
  A->>V: create desktop device/replica identity; protect capabilities
  A->>A: atomically activate profile
  A-->>U: migration report + omissions/recovery point
```

No browser CORS/localhost workaround is required. If source and destination are on the same machine, the old Docker node may be addressed through its existing local endpoint only for this explicit migration action.

## 5. Alternative migration paths

### Portable application bundle
Where the source can create `p2p_planner_bundle` v1, support import into desktop according to current format rules. This is preferable for simple planner-content portability but may not capture every identity/capability property carried by node-link.

### Device-link/2
Use for provisioning a desktop device from an already trusted mobile/native device when the protocol covers the desired identity/capability scope. Do not overload device-link into a generic DB clone.

### Export to removable/offline media
In constrained networks, logical bundle/node-link material can be written to removable media if the format supports safe offline transfer. Sensitive provisioning material must be encrypted/authenticated according to its protocol; plain planner export must not accidentally acquire session/deployment secrets.

## 6. Migration acceptance invariants

Before activating the destination:
- destination is empty or a separately named fresh profile;
- transfer/export version supported;
- payload size/count/depth limits pass;
- no contradictory duplicate entity IDs/types;
- workspace/board ownership graph valid;
- all required parent references resolve or are explicitly allowed tombstoned references;
- tombstone/version ordering invariants pass;
- capability board/workspace IDs and epochs are consistent;
- checklist/card roaming versions pass known conformance vectors;
- import is atomic/staged; source failure cannot leave half-migrated active profile;
- a fresh desktop device/replica identity is created instead of copying server/browser session state; any remote HTTP session is provisioned separately;
- backend deployment secrets are absent from SQLite, vault and logs;
- destination can create a portable logical export that re-imports into a disposable test profile;
- if Android/web coexist, sync smoke test shows no duplicate logical board/user identity.

## 7. Shared-workspace limitation

**[FACT]** web-node-link v1 omits shared workspaces.

The migration UI/report must make this visible before cutover. First GA may require those workspaces to be re-invited/re-provisioned after migration. A future signed membership/capability export needs its own authorization/revocation design; copying PostgreSQL membership rows directly is explicitly rejected.

## 8. Password/session/secret semantics

The migration/device-link flow proves control of the source identity/capabilities. The new desktop receives its own device/replica state. Local UI access does not require a self-issued JWT session.

Never copy:
- password hashes as a desktop login shortcut;
- browser cookies;
- active backend access/refresh tokens unless a protocol explicitly provisions a fresh one;
- JWT signing secret;
- deployment Nostr signing secret;
- global backend master key;
- source-machine keyring blobs.

Arch desktop stores new refresh/capability secrets through Secret Service or the explicit passphrase vault fallback.

## 9. If only a PostgreSQL dump remains

A raw PostgreSQL dump is a legacy DR artifact, not a desktop import format.

Supported recovery order:
1. restore the dump into a matching legacy p2pKanban/PostgreSQL environment and emit a canonical logical node-link/bundle export;
2. provide a separately versioned **operator** migrator for known legacy schemas that emits canonical logical data;
3. if schema/version cannot be verified, stop rather than guessing table semantics.

The operator recovery environment may use a pinned PostgreSQL package/container/VM if necessary, but this is a one-time recovery tool and never becomes a normal dependency of the Arch desktop client.

For Russian/offline resilience, retain release notes/checksums and enough legacy recovery instructions/artifacts to reconstruct the supported old environment without depending on a single live registry. Do not disable signature verification to achieve this.

## 10. Docker → desktop cutover checklist

1. Inventory current web/backend version, PostgreSQL schema/migrations and owned/shared workspaces.
2. Create/verify the existing PostgreSQL backup before touching the legacy deployment.
3. If safe and already available, move the legacy node to the newest supported migration-source release.
4. Install signed Arch package from repository/offline package set; fully update system coherently if required—never create a partial-upgrade state.
5. Create a new empty desktop profile.
6. Run logical migration with old node still available and writable only as needed.
7. Compare source/destination logical counts and selected canonical hashes/snapshots.
8. Verify labels/comments/checklists/tombstones/appearance and capability epochs.
9. Disconnect network and prove local create/move/archive/checklist operations persist.
10. Reconnect and prove synchronization with at least one existing Android/web-compatible replica when available.
11. Create desktop internal backup plus portable export.
12. Keep the legacy node stopped/read-only but recoverable for an agreed rollback window.
13. Remove Docker/PostgreSQL deployment only after acceptance; desktop migration never uninstalls Docker or deletes old volumes automatically.

## 11. Coexistence rules during transition

- Do not independently edit an old unsynchronized clone after final cutover unless it intentionally participates as a supported replica/node.
- Copying a DB directory does not create a legitimate new replica identity.
- Each desktop installation/profile receives its own device/replica identity.
- Event IDs remain globally unique and replay idempotent.
- Capability epoch/tombstone semantics apply uniformly across web/Android/desktop.
- Device-local reminders/hides/window preferences remain local.
- A relay outage can delay convergence but must not redefine ownership/authorization/merge rules.
- package updates on Arch do not imply protocol updates; mixed app versions remain supported only within declared compatibility windows.

## 12. Compatibility proof suite — [PROPOSAL]

Check in canonical, network-independent fixtures consumed by Rust backend/desktop tests and mirrored by Android TypeScript tests:
- signed `p2p-kanban-sync/1` envelope;
- roaming board-tag derivation vector;
- XChaCha20-Poly1305 roaming encrypt/decrypt vector;
- merge tie-break `logicalClock → replicaId → eventId`;
- card/checklist/item tombstone cases including stale resurrection attempts;
- capability epoch grant/revoke/stale-writer cases;
- device-link/2 grant/request/response signature, expiry and delegation constraints;
- `p2p_planner_bundle` v1 roundtrip fixture;
- web-node-link v1 fixture including explicit omitted fields;
- malformed/oversize/deep/unknown-version rejection corpus.

This fixture suite is a stronger compatibility contract than forcing all clients to share one implementation language or database.

## 13. Binary/protocol compatibility classification

| Layer | Preserve exactly? | Strategy |
|---|---|---|
| Stable UUID strings and protocol constants | yes | canonical fixtures/tests |
| Signed/encrypted event binary/JSON representation where protocol specifies | yes | golden vectors |
| Export/node-link JSON fields/version | yes for supported version | parser + roundtrip tests |
| PostgreSQL schema/storage bytes | no | logical migration only |
| Android AsyncStorage snapshot bytes | no public promise | semantic import only if later specified |
| Desktop SQLite bytes | no public promise | internal backup only |
| Secret Service/KWallet item representation | no | vault adapter private detail |
| Package file format | Arch-specific | pacman/AppImage release contract |


## A10 compatibility correction

**[FACT — A10 correction]** Source inspection supersedes two stale A00 fixture details: web `sync/1` rejects generic `put` and Android `roaming/1` wraps card state under `payload.card`. The fixtures are corrected rather than widening either protocol. A fixed synthetic Android crypto vector plus seed-only `board.snapshot`, replay/tombstone and capability-epoch tests now form the desktop conformance gate. Legacy roaming/1 still has no post-snapshot column mutation operation; native fails such markers closed. A10 additionally carries the A09b fresh-host Cargo correction (`getrandom 0.4.3` → `0.4.2`) and a deterministic relay-disruption convergence harness; neither change alters wire protocol semantics.
