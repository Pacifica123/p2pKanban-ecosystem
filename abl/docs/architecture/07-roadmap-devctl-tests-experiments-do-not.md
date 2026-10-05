# 07 — Staged implementation roadmap, devctl boundaries, tests, experiments and “не делать”: Arch Linux

## 1. Delivery principle

The implementation sequence is intentionally vertical and evidence-driven. Do not start with “port all SQL” or “rewrite UI.” First establish contracts and seams, then prove one usable offline slice, then add compatibility/sync, then harden packaging/lifecycle.

Every stage should be deliverable as one or a small bounded series of devctl patch ZIPs with deterministic checks. Network-dependent/manual tests belong in explicit acceptance gates and UserTestSpace, not hidden in an otherwise deterministic patch check.

## 2. Patch sequence

| Patch | Scope | Vertical result | Required checks / exit evidence |
|---|---|---|---|
| A00 | evidence baseline + protocol fixtures | current semantics frozen before refactor | source inventory, migration digest, canonical sync/roaming/device-link/export fixtures |
| A01 | Tauri 2 shell + packaged React/Vite asset | native Arch window opens offline | build/typecheck, no remote navigation, no Docker/Node runtime on test host |
| A02 | frontend transport adapter | UI can switch HTTP(web) vs typed IPC(desktop) | `apiRequest` callers unchanged where practical; no privileged direct WebView API |
| A03 | Rust application/domain boundary | Axum logic begins separating from HTTP/PG | legacy PG tests still green; no `sqlx::Pg*` in extracted domain APIs |
| A04 | repository contract suite | semantic behavior executable against adapters | CRUD/order/tombstone/capability/transaction scenarios defined independent of SQL |
| A05 | SQLite profile schema + migration engine | durable local profile opens/reopens | FK/WAL/FULL, schema metadata, backup+journal, integrity tests |
| A06 | XDG profile/config/state/cache adapters + single instance | correct Arch filesystem/process behavior | temporary XDG test dirs, lock/second-instance routing, no writes to `/usr` |
| A07 | auth/workspace/board minimal slice + vault interface | sign in/provision, create/open board, offline reopen | access token memory-only, fake/in-memory vault contract, offline persistence |
| A08 | cards/order/archive/delete/checklists | core planner useful fully offline | transaction + pending queue + tombstones + crash injection |
| A09 | Linux Secret Service + passphrase/session fallback | production secret persistence | present/locked/absent provider matrix; secret canary scan; Argon2id params versioned |
| A10 | `sync-core` + Nostr roaming compatibility | desktop converges with existing protocol | golden vectors, relay drop/reorder/replay harness, capability epoch tests |
| A11 | device-link/2 + web-node-link/bundle import | native provisioning and Docker migration | empty-profile staged import, no deployment secrets, roundtrip/export proof |
| A12 | labels/comments/activity/appearance parity | broad current-web feature parity | application contract suite + explicit parity ledger |
| A13 | Wayland/X11, notifications, deep links, tray capability detection | desktop UX integration | KDE/GNOME Wayland + X11 matrix; no-tray/no-notification graceful behavior |
| A14 | optional bounded LAN compatibility bridge | only remaining legacy pairing gap | off-by-default, TTL/one-time auth/rate/size tests, no firewall mutation |
| A15 | PKGBUILD + signed repo packaging | pacman-owned install/update/uninstall | clean-chroot build, `namcap`, `pacman -Qkk`, uninstall preserves XDG data |
| A16 | backup/doctor/safe-mode/recovery | user can recover without WebView/Docker | corrupt DB/runtime/disk-full/migration-failure drills |
| A17 | AppImage fallback + offline release kit | secondary install/recovery channel | signature/hash verification, FUSE + extract/run path, no package-state confusion |
| A18 | performance/power/rolling-release hardening | GA candidate | budgets measured, WebKitGTK transition canary, suspend/network chaos |
| A19 | Iroh/Arch ARM experiments | optional evidence only | no promotion without success criteria; failures cannot affect GA path |

**Ordering invariant:** A03/A04 precede serious A05+ data porting. Otherwise PostgreSQL-specific semantics will leak directly into the SQLite implementation and become harder to review.

**[FACT — implementation status]** A03 and A04 are now present in the Arch-native repository. A04 provides a pure Rust reference adapter and reusable semantic scenarios; SQLite execution of those same scenarios remains the A05 gate, so this status does not claim dual-adapter persistence verification yet.

**[FACT — implementation status after A09 source gate]** A05/A05b, A06, A07/A07b and A08 are user-reported UTS-green. A09 implements the production secret storage/provider boundary: Secret Service-protected vault root when available/unlocked, versioned Argon2id passphrase provider, AEAD-encrypted typed secret file and fail-closed session-only degradation. Multi-host GNOME/KWallet/minimal-session evidence is still experiment-needed. A08 pending markers are not remote convergence; A10 owns sync.

## 3. Suggested devctl patch discipline

The provided devctl is v0.7.0 and already gives a suitable safety conveyor: validated manifest/safe paths, pre snapshot, declared checks, commit/push policy from workspace, failed archive/reset and UserTestSpace.

Each desktop patch should:
- use `formatVersion: 1` manifest and a stable unique `patchId`;
- declare only intended `files/` payload and explicit deletes;
- set target `expectedFiles` when useful to avoid wrong-workspace application;
- exclude `target/`, `node_modules/`, `dist/`, package artifacts, XDG runtime data, `.env*`, SQLite DBs, secrets, keyrings and signing material from patch/archive payloads;
- include a concise `PATCH_SUMMARY.md` with: decision/ADR IDs, touched boundaries, schema/protocol impact, rollback story, known experiment flags;
- keep deterministic checks offline-capable whenever possible;
- place network/GUI/package-manager/manual experiments in named acceptance scripts/checklists run in UserTestSpace;
- never include private signing keys, repository keys, test refresh tokens or real board keys.

### Patch categories and mandatory extras

**Schema patch** → old/new DB fixture, migration ID/checksum, forward migration test, failed-migration restore test, min reader/writer statement.  
**Protocol patch** → updated golden vectors, backward/forward compatibility note, unknown-version rejection test.  
**Packaging patch** → PKGBUILD/package metadata diff, clean-chroot build log, package file list/ownership check, artifact hash; no binary signing private material.  
**Security patch** → threat boundary changed, secret/redaction test and fail-closed test.  
**OS-integration patch** → Wayland/X11/desktop-environment support table and degraded-mode behavior.

## 4. Core acceptance gates

### Gate A — native/offline shell
- fully updated clean Arch x86_64 host;
- no Docker/Podman/PostgreSQL/Node/Rust installed as runtime prerequisites;
- signed package installs through pacman/offline package file;
- app launches under Wayland; X11 smoke passes;
- local demo board usable with network blocked;
- no listening socket in normal mode;
- process exits when window closes unless tray mode explicitly enabled.

### Gate B — storage correctness
- 100+ forced kill/restart iterations around mutations;
- SQLite `foreign_key_check` + `integrity_check`/`quick_check` clean;
- migration N→N+1 and forced-failure restore proven;
- old app refuses unsupported newer writer schema;
- 10k-card and 100k pending-operation fixtures stay within latency/storage budgets;
- live DB on unsupported NFS/FUSE path is rejected/warned according to policy rather than silently assumed safe.

### Gate C — cross-client compatibility
- web/backend v2 ↔ Arch `sync/1` fixture;
- Android ↔ Arch `roaming/1` crypto/merge fixture;
- card/checklist tombstone and stale-resurrection cases;
- capability epoch revoke/stale-write cases;
- device-link/2 provisioning;
- `p2p_planner_bundle` v1 roundtrip;
- web-node-link v1 migration from representative current Docker node;
- no duplicated logical user/board identity after cutover.

### Gate D — security
- WebView navigation/CSP/IPC allowlist audit;
- IPC malformed/oversize/unknown-command fuzz;
- no token/key/passphrase in DB plaintext/log/crash/diagnostic fixture scans;
- Secret Service locked/absent handling fails closed;
- passphrase vault corruption/wrong-password behavior;
- malicious import/bundle fuzz;
- LAN bridge hostile peer/TTL/one-time-token tests;
- package/AppImage signature/hash tamper/replay tests.

### Gate E — Arch lifecycle/integration
- KDE Plasma Wayland, GNOME Wayland, at least one X11 session;
- notifications present/absent;
- StatusNotifier host present/absent;
- Secret Service present/unlocked, present/locked, absent;
- portal/file chooser path available/unavailable as applicable;
- suspend/resume × Wi-Fi/Ethernet/VPN/offline switching;
- second-instance + deep link/file-open routing;
- read-only/full disk/permission failures;
- no automatic polkit/firewall/systemd-linger modifications.

### Gate F — packaging/rolling release
- `makepkg`/devtools clean-chroot reproducible build procedure;
- `namcap` and package-file ownership review;
- install/upgrade/remove through pacman on coherent fully updated system;
- application never writes package-owned `/usr` files;
- uninstall preserves XDG data/secret entries;
- package downgrade is blocked or paired with compatible DB restore rules;
- canary after major WebKitGTK/GTK/OpenSSL/glibc transition;
- unsupported partial-upgrade state produces clear `doctor` diagnosis, not hacks.

### Gate G — GA
- measured startup/memory/CPU/wakeup/disk budgets pass or deviations have accepted ADR;
- real representative Docker→desktop migration drill passes;
- offline install/recovery kit verified without primary project origins;
- restore from last verified backup passes;
- package/release can be reconstructed from retained source/lock/cache metadata;
- open high-severity security/data-loss risks = 0.

## 5. Test strategy

### Unit tests
- domain validation and ordering;
- deterministic merge comparator;
- field version/tombstone logic;
- capability epoch authorization;
- repository transaction semantics;
- schema reader/writer negotiation;
- XDG path resolution;
- secret record format/key derivation/rotation;
- redaction;
- signed release metadata verification.

### Property/fuzz tests
- duplicate event replay is idempotent;
- arbitrary event ordering produces deterministic outcome under protocol rules;
- older mutations cannot resurrect valid tombstones;
- unknown/oversize nested import/IPC payloads are bounded/rejected;
- device-link delegation/expiry chain constraints always hold;
- migration interruption cannot expose partially activated profile;
- filename/deep-link values never become shell commands.

### Repository contract tests
Run one logical scenario suite against:
1. current PostgreSQL adapter during extraction;
2. SQLite desktop adapter.

Assert semantic result, authorization, ordering, tombstones and transaction boundaries—not identical SQL shape. PostgreSQL-only infrastructure behavior such as `SKIP LOCKED` must be represented as an application queue semantic before implementing the SQLite equivalent.

### Integration tests
- Tauri IPC ↔ Rust core ↔ SQLite;
- WebKitGTK packaged asset + forbidden remote navigation;
- XDG directories/permissions/single-instance lock;
- Secret Service mock/real provider + passphrase fallback;
- Nostr relay harness with disconnect/drop/reorder/replay;
- notification/deep-link callbacks;
- backup/restore/safe mode;
- package metadata/install tree.

### End-to-end scenario
1. install package as ordinary user;
2. migrate a supported Docker node into empty profile;
3. disconnect all network;
4. edit/move/archive cards and checklists;
5. close/reopen app and verify durable local state;
6. suspend/resume, switch VPN/Wi-Fi/offline;
7. reconnect and converge with Android/web-compatible replica;
8. update package to build with DB migration;
9. inject migration/startup failure and restore compatible snapshot;
10. export portable bundle;
11. remove package and reinstall; retained XDG profile reopens;
12. run `doctor` with WebKitGTK/keyring capability failures.

### Chaos/fault injection
- SIGKILL around transaction/migration/import phases;
- power/suspend during WAL activity;
- disk full/read-only `$HOME`;
- corrupted WAL/DB/backup manifest;
- missing `$XDG_RUNTIME_DIR` edge case;
- session D-Bus disappears/restarts;
- Secret Service locks/disappears;
- notification/tray host disappears;
- relay hostile/unreachable;
- DNS/VPN route changes;
- bad wall clock;
- expired/revoked capability;
- WebKitGTK loader/start regression simulation;
- second-instance storm;
- AppImage without FUSE.

## 6. Experiments required before locking decisions

| ID | Experiment | Exit criterion |
|---|---|---|
| EX-ARCH-001 | Tauri/WebKitGTK memory/startup/power vs current Docker path and Electron control | aggregate process-tree budgets credible on 8–16 GiB laptop |
| EX-ARCH-002 | SQLite WAL FULL vs NORMAL | retain FULL unless measured UX cost is material and a durability ADR accepts change |
| EX-ARCH-003 | extract hardest PostgreSQL queries/jobs into repository/application semantics | no PG-specific type/operator leaks into domain contract |
| EX-ARCH-004 | SQLite on ext4/btrfs plus attempted NFS/FUSE/cloud paths | define supported filesystem detector/policy from evidence |
| EX-ARCH-005 | Secret Service matrix: GNOME Keyring, KDE-compatible provider, locked/absent | reliable provider detection + secure fallback UX |
| EX-ARCH-006 | Wayland/X11/WebKitGTK regression matrix across KDE/GNOME | no release-blocking render/input/file-dialog/deep-link defect |
| EX-ARCH-007 | StatusNotifier behavior with/without host | close/tray lifecycle unambiguous; no invisible accidental daemon |
| EX-ARCH-008 | suspend/resume + NetworkManager/non-NM/VPN/offline | no lost edits; bounded idempotent reconnect |
| EX-ARCH-009 | pacman repo/signing/offline install + package downgrade/data rollback drill | ownership/trust/schema semantics proven |
| EX-ARCH-010 | AppImage on FUSE and extract/run fallback | useful fallback without weakening trust or `/usr` ownership |
| EX-ARCH-011 | WebKitGTK/GTK/glibc rolling transition canary | documented rebuild/test trigger and recoverable failure diagnostics |
| EX-ARCH-012 | Android device-link direct to desktop | decide whether LAN HTTP bridge can be omitted entirely |
| EX-ARCH-013 | Iroh under Russian ISP/VPN/NAT + suspend | only promote if measurable resilience/value over current Nostr path |
| EX-ARCH-014 | Arch Linux ARM build/runtime real hardware | only then open ARM64 support claim |

## 6.1 Open questions for implementation owner

These are intentionally unresolved. Each must be closed by evidence or a dedicated ADR rather than by incidental implementation choices.

| ID | Open question | Why it remains open | Decision trigger |
|---|---|---|---|
| OQ-ARCH-001 | Which Secret Service providers/desktop combinations are supported as tested configurations, and what fallback UX is acceptable when the collection is locked or absent? | Freedesktop API compatibility does not guarantee identical provider/session behavior. | EX-ARCH-005 on GNOME/KDE and absence/locked states. |
| OQ-ARCH-002 | What minimum WebKitGTK/GTK/glibc versions can be declared without fighting rolling-release ABI transitions? | Arch moves quickly and derivative distributions may lag or patch differently. | Clean-chroot + representative Arch/EndeavourOS/Manjaro canary data across several transitions. |
| OQ-ARCH-003 | What exact support promise should the AppImage fallback make? | FUSE availability, glibc baseline, WebKit/system integration and update semantics differ from pacman-native delivery. | EX-ARCH-010 plus signed offline install/recovery drill. |
| OQ-ARCH-004 | Is a systemd --user background service ever justified? | Single-process lifecycle is simpler and avoids invisible battery/network use; background sync may later become a product requirement. | Explicit product need plus lifecycle/power/security ADR; never enabled silently. |
| OQ-ARCH-005 | How should tray behavior work on desktops with no StatusNotifier host, especially GNOME defaults? | A tray cannot be assumed to exist. | EX-ARCH-007; UI must remain fully operable without tray before any close-to-tray behavior ships. |
| OQ-ARCH-006 | How should shared workspaces omitted by web-node-link v1 migrate? | Current migration contract intentionally focuses on owned workspaces. | Versioned signed membership transfer/re-invite design before claiming full shared-workspace migration. |
| OQ-ARCH-007 | Is full SQLite content encryption required beyond encrypted secret records and host-disk encryption? | Whole-DB encryption changes packaging, performance, recovery and portability. | Privacy requirement plus SQLCipher/alternative experiment and backup/restore proof. |
| OQ-ARCH-008 | When should Iroh become a default transport? | Existing source is feature-gated/experimental and Linux network environments vary substantially. | EX-ARCH-013 demonstrates a material reliability benefit without harming compatibility/power. |
| OQ-ARCH-009 | When is Arch Linux ARM a supported target rather than a build experiment? | Architecture support depends on real WebKitGTK/Tauri/native dependency and packaging validation. | EX-ARCH-014 passes on real hardware and CI/release signing is reproducible. |
| OQ-ARCH-010 | What support boundary applies to EndeavourOS/Manjaro and other Arch-derived distributions? | They can differ in repository timing, kernels, desktop defaults and system-library versions. | Publish a tested-version matrix from canaries; avoid promising support based only on package-name similarity. |
| OQ-ARCH-011 | Does a local profile need an app-level passphrase lock when the desktop session is already unlocked? | Secret Service/passphrase vault protects stored keys, but an active user session has different threat assumptions. | Explicit threat model/user demand; separate unlock ADR. |
| OQ-ARCH-012 | What is the attachment/blob replication and backup contract? | Planner entities are covered; large/binary data needs size, integrity, encryption and garbage-collection rules. | Before attachments become a supported desktop migration/sync feature. |

## 7. Explicit “не делать”

1. **Не ставить Docker/Podman/PostgreSQL/Node** как скрытую runtime-зависимость native-клиента.
2. **Не делать PostgreSQL→SQLite search/replace.** Сначала domain/repository semantics and contract tests.
3. **Не считать raw PostgreSQL dump, raw SQLite или Android AsyncStorage публичным interchange format.**
4. **Не переписывать React UI целиком на GTK/Qt** без измеренной причины и отдельного ADR.
5. **Не держать localhost/LAN HTTP backend включённым по умолчанию** ради совместимости старого браузерного клиента.
6. **Не выдавать WebView raw shell/filesystem/SQL/D-Bus/keyring capabilities.**
7. **Не хранить refresh tokens/board keys/private keys в localStorage, plaintext SQLite/config/env.**
8. **Не утверждать “полное encryption-at-rest”, если защищён только secret vault.**
9. **Не переносить JWT signing/global master/deployment Nostr secret/browser session из Docker node.**
10. **Не считать relay ACK доказательством применения/конвергенции состояния.**
11. **Не менять merge/tombstone/capability semantics только для Linux desktop без новой версии протокола.**
12. **Не делать Iroh/edge coordinator обязательным для GA**, пока они не доказаны как production dependency.
13. **Не устанавливать/enable systemd user service по умолчанию** и **не делать `loginctl enable-linger` автоматически.**
14. **Не менять nftables/iptables/firewalld/ufw/polkit автоматически.**
15. **Не требовать tray/notification/portal/Secret Service для базовой работы.** Их отсутствие — поддерживаемый degraded mode.
16. **Не писать/обновлять `/usr` из приложения** при pacman-установке.
17. **Не запускать `pacman -Sy`, selective partial upgrade или автоматический system downgrade.**
18. **Не подсовывать приватные копии системных GTK/WebKit/OpenSSL библиотек через `LD_LIBRARY_PATH` как “фикс” rolling ABI.**
19. **Не считать `pacman -U old.pkg` достаточным DB rollback.** Schema/data compatibility проверяется отдельно.
20. **Не удалять XDG profile/config/state/keyring data обычным `pacman -R`.**
21. **Не полагаться на FUSE/AppImage как единственный канал установки.**
22. **Не привязывать runtime к Docker Hub/GitHub/npm/crates.io/одному relay/CDN.**
23. **Не обходить PGP/hash/TLS/signature checks из-за сетевых ограничений.**
24. **Не поддерживать Arch partial-upgrade состояния ценой небезопасных workaround.** Диагностировать и требовать coherent system state.
25. **Не абстрагировать Windows и Arch packaging/secrets/lifecycle до общего слоя, который скрывает реальные OS-инварианты.**

## 8. Definition of “native Arch replacement”

The implementation is ready to replace the current browser+Docker path only when an independent tester can:
- start from a coherent fully updated Arch x86_64 system without Docker/PostgreSQL/Node runtime;
- install a signed package (or verified offline package set) and launch under Wayland;
- migrate a representative current Docker node using a logical supported contract;
- work for an extended period offline with durable edits;
- synchronize with an Android/web-compatible node after reconnect;
- survive suspend, VPN/network switching, missing tray/notification/keyring variants;
- update via pacman without the application mutating `/usr`;
- prove package rollback/data rollback semantics with a failed migration drill;
- recover/export data using `doctor`/safe mode even if WebKitGTK fails;
- uninstall/reinstall without unintended data loss;
- show through process/socket/dependency inspection that there is no hidden external local runtime or always-on daemon.


**[FACT — implementation status after A10 source gate]** A09b removed the yanked AEAD dependency, but fresh-host UTS exposed a second exact `getrandom 0.4.3` offline resolver conflict; A10 corrects it to 0.4.2 while keeping the final offline re-resolution gate strict. A10 implements the local sync-core/roaming compatibility boundary, schema v4 protocol state, deterministic Android/web conformance vectors and a transport-simulation drop/reorder/replay convergence harness. A live Nostr relay coordinator and device-link provisioning are not claimed; A11 remains next after A10 UTS.
