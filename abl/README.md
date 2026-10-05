# p2pKanban Arch Native

Dedicated Arch-based Linux desktop implementation of p2pKanban.

This repository follows the implementation sequence `A00 … A19` from the accepted Arch-native architecture. The normal runtime target is **Tauri 2 + system WebKitGTK + one in-process Rust core + SQLite**, with no mandatory Docker, PostgreSQL, Node runtime, localhost backend, root helper or system service.

## Current state

A00–A16 code is present. The latest supplied archive includes A16 doctor/backup/safe-mode/recovery; its real-binary host acceptance remains separately recorded. A17 now adds the optional AppImage build channel and signed offline installation/recovery kit. The normal pacman path remains A15.

See [A17 offline-kit instructions](docs/A17_OFFLINE_KIT.md) and [A16 recovery](docs/A16_RECOVERY.md). A17 signature/tamper behavior is tested with synthetic artifacts; an actual built AppImage, FUSE/extract launch, WebKitGTK and distribution baseline must pass the explicit release/host gates before a binary is described as supported. Next implementation stage: **A18 — performance/power/rolling-release hardening**.

## Source layout

- `src/` — React presentation source.
- `src-tauri/` — native Tauri shell source and deny-by-default WebView policy.
- `docs/architecture/` — implementation-driving architecture and ADR/debt corrections.
- `docs/IMPLEMENTATION_STATUS.md` — decision → files/tests → status → next patch traceability.
- `docs/evidence/` — frozen source facts plus implementation/UTS evidence boundaries.
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

## 2026-10-01 correction

See [A17b UTS cache recovery](docs/A17_UTS_CACHE_RECOVERY.md).
