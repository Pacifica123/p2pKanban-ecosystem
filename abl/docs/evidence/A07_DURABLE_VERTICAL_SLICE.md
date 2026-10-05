# A07 — durable workspace/board vertical slice + vault boundary

**Status: implemented; first canonical UTS run exposed two compile defects corrected by A07b. Post-fix host verification remains delegated to the canonical UTS verifier.**

## Fact

- A05/A05b are UTS Cargo-green and provide the SQLite migration/repository foundation.
- A06 is UTS-green and acquires one writer for the default XDG profile before Tauri startup.
- Schema v1 already stores stable workspace/board IDs and access epochs, but it has no user-facing titles.
- Architecture ADR-004 forbids durable refresh/device/board secrets in plaintext SQLite, localStorage, config or logs.

The source anchors and SHA-256 values used for this stage are recorded in `evidence/a07-vertical-slice.json`.

## Inference

A usable first native planner slice does not require card semantics yet. It requires a real composition path from packaged React UI through typed IPC and an application service into the durable XDG SQLite profile. Secret storage must have an interface before any durable auth/capability material is introduced, but production Secret Service/passphrase providers do not need to be fabricated at A07.

## Proposal implemented by A07

- schema v2 adds `workspaces.title` and `boards.title`, preserving existing stable IDs and epochs;
- v1→v2 is an explicit checksum-addressed migration: `desktop-0002-workspace-board-titles` / `01cdfaa3b020e1fbab4abbd45640f0726aa43d08bd1f20837856300dedbe1901`;
- schema v2 sets `min_reader=2` and `min_writer=2`: A07 does **not** advertise binary downgrade to the A05 reader;
- `WorkspaceCatalogRepository` and `WorkspaceService` provide create/list/open semantics without importing Tauri, SQLite, filesystem or network APIs into application/domain;
- `SqliteWorkspaceCatalog` implements that contract behind the infrastructure boundary;
- new entity IDs are UUIDs generated inside the Rust application process, not by the WebView;
- the Tauri adapter exposes only allowlisted typed commands for list/create/open workspace/board plus read-only vault status;
- the React shell now provides a real local scenario: create workspace → create/open board → close/reopen → select the durable objects again;
- `SecretVault` is defined before durable secret use. A07 wires only `SessionVault`; secret bytes are memory-only, not `Debug`/`Display`, and are zero-filled on drop;
- no vault put/get/delete command is exposed to the WebView. The only IPC surface is `vault status`, which reports `session-only` and `durable=false`.

## Data correctness / rollback

The v1→v2 migration uses the A05 online backup + migration journal + integrity/FK validation path. Existing v1 workspace/board IDs survive with empty titles; newly created A07 entities require non-empty titles at the application boundary. A forced migration failure restores the pre-migration database through the same profile recovery layout.

There is no reverse migration in A07. An A05 binary must refuse schema v2 rather than guess at downgrade compatibility.

## Security boundary

A07 introduces no refresh token, access token, board key, device private key or vault-root column. No secret is persisted to SQLite/localStorage. The session vault is an explicit degraded/provider-development mode, not an encryption-at-rest claim. Planner content itself remains plaintext SQLite and is outside ADR-004 secret protection.

Remote login/JWT is deliberately absent: local Tauri IPC is bound to the opened user profile and does not authenticate itself with browser cookies or a local JWT.

## Tests

Rust tests cover:

- application service title validation and create/open flow without platform dependencies;
- session-vault typed memory roundtrip and session-only status;
- v1→v2 migration preserving workspace/board identity;
- workspace/board create → close SQLite connection → reopen → retrieve the same objects;
- board creation scoped to an existing workspace;
- SQLite schema canary asserting no secret-bearing column/table names.

`tools/check_a07.py` additionally guards module boundaries, migration checksum/version policy, typed command allowlist, lack of secret IPC/localStorage and UTS plan progression.

## Unresolved / later stages

- Cards/order/archive/delete/checklists remain **A08**.
- Production Secret Service/KWallet + passphrase/session fallback matrix remains **A09**.
- Remote session auth/device-link provisioning remains later compatibility work; A07 does not claim it.
- Dedicated automated WebView click/reopen evidence is not introduced; UTS Cargo tests are the durable persistence authority and the rendered scenario remains manual evidence.

The exact next architecture patch is **A08 — cards/order/archive/delete/checklists durable planner slice**.


## A07b UTS correction

The first A07 UTS run found TypeScript `TS2367` and a Rust migration-journal `format!` literal-brace error. A07b corrects those source defects without changing schema v2, persistence semantics or vault policy. The accompanying Tauri `frontendDist` error was cascading from the failed frontend build. See `docs/evidence/A07B_UTS_BUILD_FIX.md`.
