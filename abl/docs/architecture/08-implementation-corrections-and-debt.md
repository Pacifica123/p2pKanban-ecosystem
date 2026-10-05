# 08 — Implementation corrections and debt ledger

This file records implementation-time evidence that narrows or corrects the imported blueprint. Corrections are explicit; they must not be hidden in code.

## DEBT-A00-001 — devctl v0.7.0 cannot auto-reset a partially applied patch in a commitless repository

**Classification:** [FACT] from attached `devctl.py` plus an A00 dry application test.
**Architecture impact:** delivery/precondition only; no native runtime ADR is changed.
**Status:** open tooling debt; safe operational precondition defined.

The attached devctl v0.7.0 rollback path ultimately uses `git reset --hard HEAD`. In a Git repository with no commits, `HEAD` is unborn. If a patch has already copied files and then fails, the normal auto-reset cannot resolve `HEAD` and therefore cannot provide the advertised atomic rollback.

### A00 policy

The dedicated `p2pkanban-archlinux-native` target repository must have:

1. an existing seed commit on `main` before the first devctl patch is applied;
2. that seed contains `ARCH_NATIVE_REPO` with exactly `p2pkanban-archlinux-native\n`; and
3. normal Git author identity (`user.name` + `user.email`) configured so devctl can create its commit.

The sentinel is deliberately more specific than `README.md`: devctl Patch Intake uses it as target evidence, reducing the chance that A00 is routed to the existing web/Docker repository. A00 carries the same sentinel forward as a permanent repository identity marker.

### Why this is not hidden in `.devctl`

The patch must not change workspace policy or devctl itself. Therefore A00 records the limitation in the repository SSOT and tests rollback against a seeded repository. A future devctl release may remove this precondition by handling an unborn branch explicitly; when that happens this debt can be closed without changing the desktop runtime architecture.

## DEBT-A01-001 — A01 build evidence requires a provisioned Linux host; generic devctl application must remain offline-safe

**Classification:** [FACT] from the A01b construction environment and upstream Tauri Linux prerequisites.
**Architecture impact:** validation/environment only; ADR-001 remains unchanged.
**Status:** open acceptance evidence, bounded to A01c.

The patch-construction environment does not contain Cargo/rustc or WebKitGTK development metadata and cannot reach external package/registry endpoints. Installing a hidden toolchain during `devctl start`, weakening checks to a source grep, or fabricating `Cargo.lock` would all violate the repository's evidence rules and unstable-network constraint.

A01b therefore adds a fail-closed offline host harness. Dependency/cache population is an explicit build-time preparation activity outside `devctl start`; normal deterministic patch checks remain network-free. A01c must execute the strict harness and real WebView runtime probes on a provisioned Arch-family host before A01 can become `implemented`.

## DEBT-A01-002 — A01a recorded an obsolete/incorrect Tauri Rust floor

**Classification:** [FACT] from current upstream Tauri 2.11.5 workspace metadata, re-checked during A01c.
**Architecture impact:** build compatibility/evidence; ADR-001 process model is unchanged.
**Status:** source declaration corrected in A01c; host verification remains open in the canonical A02b UTS pipeline.

A01a recorded `rust-version = 1.77.2` and described that value as the selected Tauri release's Rust floor. Current upstream Tauri 2.11.5 workspace metadata declares **Rust 1.90** via `rust-version = 1.90`, and the `tauri` 2.11.5 crate inherits that workspace value. A01c therefore changes the native package declaration to `1.90` and supersedes the A01a compatibility claim.

This correction does **not** claim that 1.90 is the final reproducible build toolchain. The exact toolchain pin must be chosen from a successful Arch-family UTS build and cached/prepared explicitly so offline builds do not unexpectedly invoke rustup/network access.

## DELIVERY-A01-003 — host-dependent verification delegated to UserTestSpace

**Status:** accepted delivery-process correction; does not convert missing evidence into a pass.

The patch-construction environment may lack Cargo/Rust, Arch WebKitGTK development packages, a graphical Wayland/X11 session, or a populated offline npm/Cargo cache. Starting with A02, those unavailable host-dependent checks are explicitly delegated to UserTestSpace (UTS) when the deterministic source/contracts for the patch are green.

This changes the **blocking policy**, not the evidence claim: A01/A02 host results remain `verification-pending` until the documented UTS commands pass. Dependent source stages may proceed when they do not rely on the unverified runtime property. Any UTS failure re-opens the affected Axx stage and must be corrected before release/packaging claims. Generic devctl checks remain offline/network-independent and never turn a missing toolchain into a fake success.

## CORR-A02-004 — Tauri context required an application icon that A01/A02 omitted

**Classification:** [FACT] from the first real UTS `cargo test --locked --offline` on the A02 snapshot.
**Architecture impact:** packaging/build correctness only; no process, IPC, persistence or privilege ADR changes.
**Status:** fixed in A02b; post-fix UTS compile/launch verification pending.

`tauri::generate_context!()` failed before native tests could run because `src-tauri/icons/icon.png` was absent. This was a repository defect, not an unavailable-host limitation. A02b adds a repository-owned RGBA PNG and makes the icon path explicit in `tauri.conf.json` so the asset is part of the checked source contract rather than an undocumented Tauri default.

## CORR-A02-005 — Node `<23` build-time upper bound was unsupported by evidence

**Classification:** [FACT] from the same UTS run: Node 26.8.1 completed `npm ci`, TypeScript typecheck and Vite production build, while npm only warned about the repository's declared engine range.
**Architecture impact:** build tooling only; the packaged desktop runtime still has no Node dependency.
**Status:** corrected in A02b.

The earlier `>=20 <23` range was a conservative assumption without an implementation-driving compatibility reason. A02b removes the artificial upper bound and retains `>=20`. Future incompatibility must be based on an actual toolchain failure or upstream requirement, not an arbitrary major-version ceiling.

## DELIVERY-A02-006 — single-entry UTS verifier replaces per-patch manual command lists

**Classification:** [PROPOSAL implemented as tooling contract], motivated by repeated host-only verification steps.
**Architecture impact:** verification workflow only.
**Status:** implemented in A02b.

`tools/uts_verify.py` is now the stable UTS entry point and `tools/uts_plan.json` is the evolving machine-readable plan. Patches update the plan as host checks change. The verifier is offline by default, may populate caches only with explicit `--allow-network`, continues through independent checks, and stores text/JSON/log evidence under ignored `.uts-reports/`.

This does not weaken `devctl`: generic patch checks remain deterministic/network-free, while host/toolchain/runtime evidence remains explicit and separately attributable.

## CORR-A02-007 — deterministic hygiene confused repository content with ignored UTS build state

**Classification:** [FACT] from two consecutive real UTS verifier runs after A02b.
**Architecture impact:** verification correctness only; no runtime ADR changes.
**Status:** fixed in A02c.

The first post-A02b UTS run passed completely and intentionally left ignored `dist/`, `node_modules/`, `src-tauri/target/` and a resolver-generated Cargo lock in the working tree. The immediate second invocation then failed A00 because `dist/` merely existed, caused A01 to recursively scan generated Cargo output until the process was killed, and caused A01b to reject the current Cargo lock because it hard-coded serialization format `version = 3`.

Deterministic source gates must answer “is forbidden/generated state owned by the repository?” rather than “has this developer ever built the project?”. A02c therefore derives hygiene from `git ls-files`, scans only tracked source for forbidden runtime assumptions, and accepts resolver-generated Cargo lock formats 3/4. Ignored caches remain available for incremental offline UTS work.

## DELIVERY-A02-008 — one UTS invocation must prove post-build repeatability

**Classification:** [PROPOSAL implemented as verification tooling].
**Architecture impact:** verification workflow only.
**Status:** implemented in A02c.

The canonical verifier now reruns the entire deterministic gate list after frontend/Cargo/runtime steps. This makes state-pollution bugs observable during the same invocation that created the state. The verifier does not use `git clean`, resets, or cache deletion to manufacture a pass.


## A10 — protocol fixture corrections and roaming gap

- **Corrected:** A00 `sync-envelope-v1` used operation `put`, but the actual web sync-core allowlist does not. A10 changes it to `update`.
- **Corrected:** A00 roaming card-put payload did not match Android `service.ts`; A10 uses `payload.card` and a `deletedAt` delete payload.
- **Corrected:** future local delete pending IDs now reuse their tombstone `VersionStamp`, and future reorder emits one uniquely versioned `card.move` marker per card.
- **Unresolved compatibility debt:** `p2p-kanban-roaming/1` has no column-create/update event after initial snapshot. This is the **post-snapshot column mutation** gap. A10 blocks such pending markers; it does not invent an incompatible extension. Relay orchestration remains a later transport layer, not part of A10.


## CORR-A10-001 — A09b exact getrandom 0.4.3 pin broke fresh-host offline re-resolution

**Classification:** [FACT] from canonical A09b UTS on a different Arch-family machine.
**Architecture impact:** build/offline dependency resolution only; A09 secret-at-rest semantics and provider boundaries are unchanged.
**Status:** corrected inside A10; no separate A09c stage.

After network preparation, `cargo generate-lockfile --offline` selected `secret-service 5.2.0` against the locally cached `getrandom ^0.4` index line, where `0.4.2` was available, while the application still forced exact `getrandom 0.4.3`. The resulting resolver conflict blocked Cargo test/build even though deterministic/frontend checks were green. A10 aligns the direct pin to **getrandom 0.4.2** rather than weakening the offline re-resolution gate. `getrandom 0.4.2` remains the same 0.4 API line and satisfies `secret-service 5.2.0`'s `getrandom = "0.4"` dependency.


## CORR-A11-001 — A10 exact serde 1.0.229 pin broke fresh-host offline re-resolution

**Classification:** [FACT] from the canonical A10 UTS `cargo.lock.offline-recheck`.
**Architecture impact:** dependency resolution only; sync/roaming and SecretVault semantics are unchanged.
**Status:** corrected inside A11; no A10b/A09c stage.

After explicit network refresh, the final mandatory `cargo generate-lockfile --offline` could resolve `secret-service ^1` only against the cached `serde 1.0.228` line while the native crate forced exact `serde 1.0.229`. A11 aligns the direct application pin to **serde 1.0.228**. The verifier is intentionally not weakened: offline lock re-resolution remains a release acceptance requirement.

## CORR-A11-002 — Cargo lock offline recheck ran before network cache population

**Classification:** [FACT] from canonical A11 UTS `20260915T054436Z`.
**Architecture impact:** verifier/cache preparation only; dependency versions and A11 import/link semantics are unchanged.
**Status:** corrected inside A11; no follow-up compatibility stage.

The first A11 host UTS passed all deterministic/frontend gates but failed `cargo.lock.offline-recheck`: online `cargo generate-lockfile` selected the exact direct `serde_json 1.0.151`, while the immediate offline resolver exposed only the previously cached `serde_json 1.0.149` line to Tauri. The verifier already had a strict locked `cargo fetch` step, but it ran only **after** the offline lock recheck, so explicit network preparation updated the index/lock without populating the selected crate archives first. Chasing the host cache by pinning `serde_json 1.0.149` would make acceptance machine-history dependent.

A11 now makes Cargo preparation ordered and reproducible: initial offline lock attempt; when `--allow-network` is explicitly supplied, online lock generation followed by locked `network-fetch`; deletion of that online-created lock; mandatory `cargo generate-lockfile --offline` from the populated cache; byte-equivalence check against the online lock; then locked offline fetch/test/build. The offline re-resolution is strengthened rather than skipped.

## DEBT-A11-002 — Secret Service and SQLite do not share an ACID transaction

**Classification:** [FACT] from the platform/storage boundary.
**Architecture impact:** import crash semantics.
**Status:** bounded by fail-closed ordering and compensation; recovery/doctor hardening remains A16.

A11 performs complete validation/preflight, refuses existing vault-key collisions, writes new vault material, then commits the imported graph in one `BEGIN IMMEDIATE` SQLite transaction. Failures after vault writes trigger best-effort deletion of only those new keys. A process crash in the narrow cross-resource window can leave an unreachable orphan vault secret, but not a committed board without its required key and not a partially committed planner graph. A16 recovery tooling may enumerate/clean such unreachable material without changing this security ordering.


## CORR-A11-003 — real Cargo compilation exposed ambiguous JSON entry keys and a stale VaultStatus test initializer

**Classification:** [FACT] from canonical A11 UTS `20260915T073257Z`.
**Architecture impact:** Rust compile/test correctness only; no schema, protocol, privilege, persistence or import semantics change.
**Status:** corrected inside A11; no A11b stage.

After the cache-order correction allowed Cargo to reach actual compilation, `cargo build --locked --offline` failed on `serde_json::Map::entry("...".into())` at A10/A11 compatibility helpers. With the resolved dependency graph, the extra `.into()` leaves the generic target type ambiguous because multiple crates provide `From<&str>` candidates. A11 removes the unnecessary conversion and passes the `&str` key directly, which is the API's intended `Into<String>` input.

`cargo test --locked --offline` additionally exposed an older A09 unit-test initializer that constructed `VaultStatus` with only `mode`/`durable`, while the current A09 contract also requires `state` and `passphrase_fallback_available`. The test now constructs `VaultStatus::session_only(VaultState::ProviderUnavailable)` and asserts all four wire fields. Two imports made obsolete by A11 wiring are removed to keep the host build clean. Deterministic A11 checks now reject reintroduction of the ambiguous `Map::entry` form and require the complete VaultStatus wire regression assertion.

## DEBT-A12-001 — roaming/1 has no proven label/comment mutation operations

**Classification:** [FACT] from the frozen A00/A10 roaming operation allowlist.
**Architecture impact:** cross-device parity convergence for labels/comments.
**Status:** explicit, bounded debt; A12 does not invent a protocol extension.

A12 stores labels/comments as first-class durable native state but records each
local label/comment/card-label mutation in `parity_local_changes` with reason
`roaming-v1-unsupported`. These rows are intentionally separate from A08/A10
`pending_local_changes`: feeding an unsupported marker into A10 would either
poison materialization or tempt a silent lossy mapping. A future protocol stage
must define authenticated/versioned operations and an upgrade path before these
markers can become a real outbox.

## DEBT-A12-002 — appearance operation is proven; exact unseen legacy event body is not

**Classification:** [FACT + bounded inference] from A00/A10 source anchors and
`roaming-board-snapshot-v1` fixture.
**Architecture impact:** appearance wire representation.
**Status:** normalized A12 mapping with explicit non-claim.

The frozen compatibility evidence proves `board.appearance.put` and the snapshot
`appearance` object. The original web/Android source archives are not present in
the A12 construction environment, so the Arch adapter uses normalized
`payload.appearance` and proves its own materialize/apply behavior rather than
claiming byte-identical reproduction of an unseen legacy event body. This must be
rechecked against source before any future protocol-version or multi-client
appearance expansion.

## CORR-A12-001 — portable parity section helper returned references into temporary JSON

**Classification:** [FACT] from canonical A12 UTS `20260915T083858Z`.
**Architecture impact:** Rust compile correctness only; schema v6, parity semantics, wire compatibility, privileges and import transaction semantics are unchanged.
**Status:** corrected inside A12; no A12b stage.

The first canonical A12 Cargo run passed deterministic/frontend/offline-lock/fetch gates and then failed both `cargo test --locked --offline` and `cargo build --locked --offline` with Rust `E0515`. `section_array()` parsed an opaque portable section into a function-local `serde_json::Value` and attempted to return `Vec<&Map<String, Value>>`; those references could not outlive the local parsed value.

A12 now returns owned `Map<String, Value>` values by cloning each validated object from the parsed array. Materialization borrows those owned maps only within the caller loop, preserving the same validation, stable IDs and atomic import behavior without extending any lifetime unsafely. The only host warning observed in the same run—an unused `ParityRepository` test import—is removed as compile hygiene. `tools/check_a12.py` now rejects reintroduction of a borrowed `section_array` result.

## A13 lifecycle/integration notes

### DEBT-A13-001 — capability detection is not notification/tray delivery

A13 probes session D-Bus ownership for Desktop Notifications, StatusNotifierWatcher and the desktop portal but does not start services, create a tray icon or send arbitrary notification payloads. This is intentional: planner correctness must not depend on those services and visible tray/notification behavior still requires the KDE/GNOME/X11 experiment matrix.

### DEBT-A13-002 — package registration is deferred

The native process validates and routes `p2pkanban://` arguments, but A13 does not install a `.desktop` x-scheme-handler or MIME association. Package-owned desktop registration belongs to A15; portable bundle file-open routing remains later integration/recovery work.

### DEBT-A13-003 — deep-link navigation is an intent, not hidden repository traversal

A13 queues validated workspace/board/card identifiers and surfaces them through typed IPC. It does not invent cross-repository lookup/navigation semantics merely to auto-open an entity. Application-level navigation resolution can be added only when an explicit lookup contract exists.

## A14 bounded LAN compatibility notes

### DEBT-A14-001 — compatibility wrapper is intentionally removable

A14 exists only for the legacy LAN enrollment/migration gap. It must not become a second permanent application API. Once all supported clients can complete native device-link provisioning without this wrapper, removal is preferred over endpoint growth.

### DEBT-A14-002 — physical legacy-client interoperability remains multi-client evidence

Rust tests and the real-binary host probe prove the transport/auth/TTL/one-shot boundary and A11 destination wiring. They do not claim that every historical Android/web build already emits `p2p-kanban-lan-bridge/1`; representative physical-client pairing remains explicit compatibility evidence.

### DEBT-A14-003 — no automatic LAN discovery/firewall policy

A14 exposes detected private/link-local IPv4 addresses for explicit selection. It does not add mDNS, SSDP, UPnP, firewall rules or privilege escalation. Usability improvements must preserve that opt-in security boundary.

## A15 pacman packaging/release notes

### DEBT-A15-001 — Cargo.lock is release-owned, not yet repository-owned

Canonical UTS has historically generated `src-tauri/Cargo.lock` inside its isolated project copy and the devctl post-snapshot does not carry that generated file back into the source repository. A15 therefore does not fabricate a lock or resolve dependencies inside `build()`. `tools/a15_prepare_release.py` requires the exact UTS-accepted lock, injects it into the deterministic retained source archive and records its SHA-256 in release metadata. A future correction may promote that exact host-proven lock into repository ownership; until then, arbitrary Git checkout rebuilds are not claimed byte-reproducible.

### DEBT-A15-002 — public redistribution license is intentionally unresolved

The project snapshot supplied to A15 contains no software license. A15 must not invent one. The package therefore carries an explicit project-controlled distribution notice and public AUR/public-mirror publication remains blocked until the rights holder chooses and supplies a license. Package/repository signatures authenticate artifacts but do not grant redistribution rights.

### DEBT-A15-003 — clean-chroot/install/signing evidence changes host or uses release secrets

The canonical UTS can non-root verify release-source binding, `makepkg --verifysource`, `namcap PKGBUILD`, desktop metadata and availability of Arch packaging/signing tools. A real clean chroot requires host package/build infrastructure; pacman install/remove changes package state; official repository signing requires the external release private key. These remain named manual/release evidence and are never emulated with a committed test private key or hidden sudo invocation.

### CORR-A15-001 — Arch packaging host-preflight option/lint correction

Canonical A15 UTS on the target Arch-like host proved the packaging commands were installed but exposed two acceptance defects: `makechrootpkg` rejects GNU-style `--help` and documents the short `-h` option, while `namcap PKGBUILD` can emit `E:` diagnostics and still return success. The host probe now uses `makechrootpkg -h`, treats namcap `E:` lines as failure, and the bootstrap PKGBUILD carries a non-routable `https://example.invalid/p2pkanban` metadata URL. This correction changes only packaging acceptance/metadata; runtime, schema, protocol and release-key boundaries remain unchanged. Public publication is still blocked until project-owned origins and an approved software license replace placeholders.

### CORR-A15-002 — makechrootpkg help exit semantics

**Classification:** [FACT] from canonical A15 UTS `20260916T122445Z`.
**Architecture impact:** packaging host-preflight only; runtime, schema, protocol, package ownership and signing boundaries are unchanged.
**Status:** corrected inside A15; no A15b stage.

The target Arch `makechrootpkg -h` prints the expected usage/flags surface but exits non-zero. CORR-A15-001 corrected the option spelling but still routed the help probe through the generic `run()` helper, incorrectly treating the tool's help exit status as a capability failure. A15 now proves executable presence with the existing `shutil.which` gate and treats `-h` only as a textual sanity-check: output must contain `Usage: makechrootpkg` and `Flags:` regardless of the help command exit code. This preserves fail-closed detection of a wrong/unexpected executable without imposing GNU-style help exit semantics on Arch devtools.

## A16 — verified profile recovery boundary

A16 adds recovery without widening the WebView privilege surface or changing schema/protocol contracts. The normal startup path performs a read-only doctor while it already owns the profile writer flock; if an older supported schema is healthy, A16 creates a verified connection-level pre-migration profile snapshot before any repository performs the existing writable migration. The A05 migration engine and its transaction-local rollback artifact remain unchanged.

CLI recovery uses a separate native flock guard on the same profile directory, deliberately without binding or routing through the A06/A13 graphical activation socket. `doctor`, `backups`, `safe-mode`, `safe-export` and confirmed `restore` therefore remain usable without constructing the WebView or starting A14 LAN compatibility transport. Restore verifies the immutable snapshot manifest/hash/integrity first, preserves a healthy pre-restore point when possible, quarantines the replaced DB/WAL/SHM/journal, atomically installs the verified snapshot, then rechecks integrity and hash.

### DEBT-A16-001 — canonical Rust/real-binary acceptance is host-owned

**Classification:** [FACT] from the patch-construction environment.
**Architecture impact:** evidence only; recovery semantics are implemented in source.
**Status:** open until canonical A16 UTS passes.

The construction environment used for this patch has Python/Node but no `cargo`, `rustc` or `rustfmt`. It can execute deterministic source/contracts but cannot truthfully claim Rust compilation or the real-binary recovery drill. Canonical UTS therefore adds both `cargo test ... a16_` and `tools/a16_host_recovery_probe.py`; a failed compile/probe reopens A16.

### DEBT-A16-002 — recovery logical export is salvage, not a new interchange contract

**Classification:** [PROPOSAL implemented with an explicit compatibility boundary].
**Architecture impact:** export/recovery semantics; A11 public portable format remains unchanged.
**Status:** intentional boundary.

`p2pkanban safe-export` emits `p2pkanban-recovery-logical` v1 containing known planner-content tables that can be read safely from an integrity-valid profile. It intentionally excludes profile principal/capability/import receipts, sync outbox/seen/field-version state, pending mutation markers and schema bookkeeping. It is not advertised as `p2p_planner_bundle`, is not directly importable, and does not supersede A11 portable interoperability. Its purpose is human/support salvage when the normal UI/runtime path is unavailable.

### DEBT-A16-003 — runtime/package repair remains non-privileged

**Classification:** [ARCHITECTURE constraint].
**Architecture impact:** safe-mode scope.
**Status:** bounded/open for later release diagnostics.

A16 does not run `pacman`, `sudo`, `pkexec`, download replacement WebKit libraries or disable signature/TLS checks. A healthy `p2pkanban doctor` result separates profile health from a later WebView/runtime failure, but a loader failure that prevents the executable itself from entering `main` necessarily remains a package-manager/runtime-support problem. A17/A18 may improve offline runtime diagnostics; they must not turn recovery into a self-updater or privileged repair agent.
