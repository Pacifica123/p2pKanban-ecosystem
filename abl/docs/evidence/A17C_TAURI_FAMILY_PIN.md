# A17c — Tauri family pin (CORR-A17-001)

## Observation

First canonical UTS after the move into the `p2pKanban-ecosystem` monorepo
(run `20261006T044732Z`): `overall: FAIL`. `cargo.test` and `cargo.build`
failed; all `host.*` probes and `runtime.launch-probe` were BLOCKED behind
them. Deterministic and frontend steps passed.

`cargo.test.log` shows the resolved family: `tauri 2.11.5` with
`tauri-runtime 2.12.1`, `tauri-runtime-wry 2.12.1`, `tauri-codegen 2.7.1`,
`tauri-macros 2.7.1`. `cargo.build.log` fails in
`tauri-2.11.5/src/app.rs:873` (`match` arms have incompatible types:
`Option<Monitor>` vs the 2.12 runtime API).

## Cause

Only `tauri` and `tauri-build` were exact-pinned. Tauri 2.11.5 requires the
rest of its family with caret ranges, and the UTS lock re-resolution (by
design not weakened, see CORR-A11-002) picked the newest 2.12-era crates.

## Correction

Exact pins in `src-tauri/Cargo.toml`:

| crate | version |
|---|---|
| tauri-runtime | =2.11.3 |
| tauri-runtime-wry | =2.11.4 |
| tauri-macros | =2.6.3 |
| tauri-codegen | =2.6.3 |
| tauri-utils | =2.9.3 |

`Cargo.lock` regenerated; it now carries `wry 0.55.1` and `tao 0.35.3`.

## Evidence

- cloud host with WebKitGTK 4.1 dev libraries: `cargo generate-lockfile`
  from scratch selects exactly this family; `cargo build --locked` passes;
  `cargo test --locked` passes 121 tests;
- `tools/check_a17c.py` asserts the pins in both `Cargo.toml` and
  `Cargo.lock` and is part of the deterministic UTS plan;
- all `tools/check_a*.py` pass (A14 evidence digest for `Cargo.toml`
  updated).

## Not claimed

Canonical host UTS (`python3 -B tools/uts_verify.py`), host probes and the
launch probe on Arch are still the acceptance gate for A15–A17.
