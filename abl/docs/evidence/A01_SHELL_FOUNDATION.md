# A01 shell foundation evidence

A01 is intentionally split into two bounded devctl patches. This file records the first one, **A01a**. It adds the final-form shell source/security boundary without inventing build evidence that was not obtainable in the patch-construction runner.

## Classification

### FACT

- The A00 web evidence uses React/Vite and its locked frontend resolves React `18.3.1` / React DOM `18.3.1`; A01a keeps those presentation-major semantics instead of upgrading the UI while changing the process model.
- The accepted SSOT selects Tauri 2 + system WebKitGTK, one normal user-session process, no mandatory localhost backend and no mandatory service.
- **Superseded by A01c / DEBT-A01-002:** A01a recorded Tauri's Rust floor as `1.77.2`. Re-checking the selected Tauri `2.11.5` upstream workspace during A01c shows `rust-version = "1.90"`; the project manifest is corrected accordingly.
- Tauri 2 exposes `WebviewWindowBuilder::on_navigation` and `on_new_window`; A01a uses those Rust-side hooks rather than relying only on DOM code.
- The patch-construction runner has Node/npm but no Rust/Cargo toolchain and no crates cache. Network access to npm/crates/static Rust endpoints is unavailable. Therefore a trustworthy project `Cargo.lock` and a real Tauri compile cannot be generated or asserted here.

### INFERENCE

- Keeping the A01 WebView capability set empty is the narrowest safe foundation before A02 introduces an explicit typed desktop transport adapter.
- Omitting `devUrl` and loading `frontendDist` through `WebviewUrl::App` removes a localhost development server from the normal shell model and keeps packaged assets as the only top-level origin.

### PROPOSAL implemented by A01a source

- One window labelled `main` is created by Rust.
- Only the `tauri:` packaged-asset scheme is accepted for top-level navigation.
- New windows and WebView downloads are denied at A01 because no trusted import/export flow exists yet.
- CSP denies network connections (`connect-src 'none'`) and frames/objects/forms; the frontend itself performs no fetch/WebSocket/localStorage access.
- The `main-minimal` capability grants no frontend-accessible Tauri commands. Filesystem, process, shell, keyring and unrestricted network plugins are absent.
- React/Vite dependencies are exact-pinned and the npm lock is derived from the reviewed web snapshot's lock resolution. It is validated offline for lock/package consistency without installing `node_modules`.

### UNRESOLVED EXPERIMENT / acceptance evidence required for A01b

A01 is **not complete** until a provisioned Arch-family build host performs all of the following without downloading during the checks:

1. materialize npm dependencies from an approved local cache/mirror and run `npm ci --offline` + `npm run build`;
2. generate and review `src-tauri/Cargo.lock` once using the selected Tauri dependency set, then preserve it in Git;
3. populate an approved Cargo cache/vendor source and run `cargo test --locked --offline` and `cargo build --locked --offline`;
4. launch the built binary with network unavailable and confirm packaged UI rendering;
5. attempt hostile HTTPS/HTTP/file/data/javascript navigation and `window.open`, confirming they are denied;
6. inspect the process/listener state and confirm no Docker, PostgreSQL, Node process, localhost listener or systemd user service is required at runtime;
7. record WebKitGTK/GTK/glibc versions and session type as environment evidence, without promoting that single host to the full Wayland/X11 compatibility claim.

These are host acceptance tasks, not hidden green checks in A01a. A01b added the strict offline build harness; A01c added the runtime evidence collector. The historical A01d materialization label is superseded operationally by the canonical A02b `tools/uts_verify.py` pipeline; the evidence itself remains required before release claims.

## A01b follow-up

A01b adds `tools/a01b_host_acceptance.py` and `docs/evidence/A01B_BUILD_ACCEPTANCE.md`. It does not retroactively convert the A01a source foundation into compiled evidence. The remaining resolver/build/launch proof is explicitly A01c.
