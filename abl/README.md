# p2pKanban Arch Native

Dedicated Arch-based Linux desktop implementation of p2pKanban.

This repository follows the implementation sequence `A00 … A19` from the accepted Arch-native architecture. The normal runtime target is **Tauri 2 + system WebKitGTK + one in-process Rust core + SQLite**, with no mandatory Docker, PostgreSQL, Node runtime, localhost backend, root helper or system service.

## Current state

A00–A16 code is present. The latest supplied archive includes A16 doctor/backup/safe-mode/recovery; its real-binary host acceptance remains separately recorded. A17 now adds the optional AppImage build channel and signed offline installation/recovery kit. The normal pacman path remains A15.

See [A17 offline-kit instructions](docs/A17_OFFLINE_KIT.md) and [A16 recovery](docs/A16_RECOVERY.md). A17 signature/tamper behavior is tested with synthetic artifacts; an actual built AppImage, FUSE/extract launch, WebKitGTK and distribution baseline must pass the explicit release/host gates before a binary is described as supported. A18 adds measured budgets, a rolling-release canary and chaos probes to the UTS: see [A18](docs/A18_PERFORMANCE_POWER_ROLLING.md). Budgets stay proposed until a release-profile run on the reference laptop; next gate: **Gate G — GA candidate**.

## Source layout

- `src/` — React presentation source.
- `src-tauri/` — native Tauri shell source and deny-by-default WebView policy.
- `docs/architecture/` — implementation-driving architecture and ADR/debt corrections.
- `docs/IMPLEMENTATION_STATUS.md` — decision → files/tests → status → next patch traceability.
- `docs/evidence/` — frozen source facts plus implementation/UTS evidence boundaries.
- `docs/PROJECT_BOARD.md` — read-only project board compiled into abl (`p2p-kanban-project-board/1`).
- `evidence/` and `fixtures/` — frozen compatibility evidence for later stages.
- `tools/uts_plan.json` — evolving machine-readable UserTestSpace verification plan.
- `tools/uts_verify.py` — stable single-entry UTS runner.

## Deterministic devctl checks

`devctl start` uses network-free source/contracts gates only. A02b adds:

```bash
python3 -B tools/check_a02b.py
```

## UserTestSpace host verification

Run one command from the UTS project root:

```bash
python3 -B tools/uts_verify.py
```

If the summary reports missing npm/Cargo cache entries and build-time network preparation is acceptable:

```bash
python3 -B tools/uts_verify.py --allow-network
```

Reports are written under ignored `.uts-reports/`; send `latest-summary.txt` and the referenced failing log when a check fails. See `docs/UTS_VERIFICATION.md`.

A15 pacman acceptance (clean chroot, signed repository, `pacman -Qkk`, removal keeps user data) is a receipt the host issues for itself, once per abl source change, in a terminal because it needs sudo:

```bash
python3 -B tools/a15_issue_receipt.py --signing-key <release key fingerprint>
```

`--dry-run` lists every privileged command first; `--no-build` reuses the package of an earlier receipt for the same sources. The UTS step `host.a15-release-receipt` only reads the receipt: PASS while it matches this tree and the installed package, SKIP with the command to run otherwise. See [A15 Arch release](docs/A15_ARCH_RELEASE.md#0-the-a15-release-receipt).

## 2026-10-01 correction

See [A17b UTS cache recovery](docs/A17_UTS_CACHE_RECOVERY.md).
