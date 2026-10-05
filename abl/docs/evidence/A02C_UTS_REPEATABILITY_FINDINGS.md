# A02c — UTS repeatability correction

**Status: implemented tooling correction; application architecture remains at A02 pending A03.**

## FACT — evidence supplied from real UserTestSpace

The first post-A02b canonical UTS run on a real Arch-family workstation completed with `overall: PASS`:

- Manjaro rolling, x86_64, Linux `6.18.49-1-MANJARO`, glibc 2.44;
- Wayland session;
- GLib 2.88.3, GTK3 3.24.52, WebKitGTK 4.1 / 2.52.6;
- frontend dependency preparation, TypeScript check and Vite build passed;
- Cargo lock generation/fetch, `cargo test --locked --offline`, `cargo build --locked --offline`, binary presence and runtime launch probe passed;
- the runtime process tree contained the native binary plus WebKit network/web processes and owned no TCP listening socket.

The immediately repeated run with `--allow-network` still passed frontend, Cargo test/build and runtime launch, but three *deterministic* gates failed:

1. A00 rejected the ignored `dist/` directory created by the previous successful build.
2. A01 recursively scanned `src-tauri/target/`; after about 122 seconds the check exited `-9` instead of checking repository source.
3. A01b hard-coded Cargo lock format `version = 3` and rejected the resolver-generated lock produced by the current UTS Cargo toolchain.

These are verifier/repository-contract defects, not evidence of an application regression.

## CORRECTION

A02c changes deterministic hygiene semantics from “generated paths must not exist in the working tree” to “generated/runtime paths must not be **Git-tracked repository content**”. This matches the actual devctl archive policy and permits incremental UTS caches to remain between runs.

`tools/repository_contract.py` centralizes the tracked-file view. A00 and A01 use it; A01 no longer recursively reads `target/` or other ignored build output. A01b accepts resolver-generated Cargo lock formats 3 and 4 rather than asserting that Cargo-owned serialization is permanently version 3.

`tools/uts_verify.py` now reruns every deterministic gate after frontend/Cargo/runtime work. Therefore one invocation verifies that the generated UTS state did not poison repository contracts. It deliberately does **not** run `git clean`, remove Cargo/npm caches, or hide state pollution by resetting the workspace.

## NON-CLAIMS

- The generated UTS `src-tauri/Cargo.lock` is real evidence but is not silently added to this patch because its exact bytes were not supplied as a source artifact.
- Manual observation of the rendered WebView health text and dedicated hostile-navigation runtime evidence remain separate from the successful process/runtime probe.
