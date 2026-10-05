# A02b — UTS build findings and corrections

## FACT — 2026-09-12 UserTestSpace run

The A02 snapshot was exercised on an Arch-family rolling host reported by the existing doctor as Manjaro Linux, x86_64, glibc 2.44, Wayland, GTK 3.24.52 and WebKitGTK 2.52.6.

Observed results:

- A00/A01/A01b/A01c/A02 deterministic gates passed;
- `npm ci`, TypeScript typecheck and Vite production build passed;
- Node 26.8.1 only produced an `EBADENGINE` warning because the repository had an artificial `<23` upper bound;
- `cargo generate-lockfile` succeeded and resolved 431 packages;
- `cargo fetch --locked` succeeded;
- `cargo test --locked --offline` reached the native package but `tauri::generate_context!()` aborted because `src-tauri/icons/icon.png` did not exist.

The compiler failure is direct evidence that A01/A02 were not yet build-accepted. It is not treated as an environment skip.

## CORRECTION

A02b:

1. adds a repository-owned 64×64 RGBA `src-tauri/icons/icon.png` and explicitly declares it in `tauri.conf.json`;
2. removes the unsupported Node `<23` upper cap while keeping Node `>=20` as a build-time floor; Node remains absent from the application runtime architecture;
3. adds `tools/uts_verify.py` + `tools/uts_plan.json` so future patches update one verification plan while the user keeps one invocation;
4. keeps generated UTS reports ignored and outside patch/archive inputs.

## STATUS

The missing-icon defect is **implemented/fixed in source** and deterministically checked by `tools/check_a02b.py`.

A real Cargo test/build and WebView launch **after this correction** remain `verification-pending` until the next UTS verifier run. A new compiler/runtime failure must be treated as evidence and corrected before packaging/release claims.
