# A01b — offline build / Arch host acceptance harness

**Status: partially implemented.** This patch implements the strict acceptance harness and records the remaining environment evidence. It does **not** claim that A01 is complete.

## FACT

- Tauri 2.11.5 documents `WebviewUrl::App` as the packaged app URL; on Linux the custom app origin is `tauri://localhost`.
- Tauri 2.11.5 exposes Rust-side `on_navigation`, `on_new_window`, and `on_download` hooks used by A01a.
- Current Tauri Linux prerequisites require the system WebKitGTK 4.1 development stack; the upstream Arch example uses `webkit2gtk-4.1` and normal build tooling.
- `frontendDist` directory content is embedded in the production executable by Tauri rather than requiring a runtime Node/Vite server.
- The patch-construction sandbox used for A01b has Node/npm, but no `cargo`/`rustc`, no WebKitGTK development module, and no usable external package/registry egress. A resolver-generated lock or actual Tauri build therefore cannot be produced honestly in this environment.

Upstream evidence consulted during A01b:

- https://docs.rs/tauri/2.11.5/tauri/enum.WebviewUrl.html
- https://docs.rs/tauri/2.11.5/tauri/webview/struct.WebviewWindowBuilder.html
- https://v2.tauri.app/start/prerequisites/
- https://v2.tauri.app/reference/config/#frontenddist

## INFERENCE

A build gate that reports success when Cargo/WebKitGTK is absent would be weaker than A01a and would make the implementation ledger false. The correct rollback boundary is to commit the reusable, fail-closed offline acceptance harness now and materialize build/launch evidence on the provisioned Arch-family host in A01c.

## PROPOSAL implemented by A01b

`python3 -B tools/a01b_host_acceptance.py doctor` is informational and records capability facts without changing the host.

`python3 -B tools/a01b_host_acceptance.py offline-build` is strict acceptance. It requires Node/npm, Cargo/rustc, `pkg-config`, WebKitGTK 4.1, GTK3, GLib and a resolver-generated `src-tauri/Cargo.lock`; then it runs npm and Cargo with explicit offline/locked flags and verifies packaged Vite output plus the Tauri binary. Missing prerequisites are failure, never a skip.

The harness deliberately does not install packages, invoke sudo/systemd, start Docker/PostgreSQL, contact registries, or create a localhost backend.

## UNRESOLVED EXPERIMENT / host acceptance evidence

A01 remains incomplete until a provisioned Arch-family host:

1. resolver-generates/reviews `src-tauri/Cargo.lock` for the exact pinned Tauri set;
2. populates approved npm/Cargo caches as a separate build-time preparation step;
3. passes `offline-build` with external network unavailable;
4. launches the compiled app from packaged assets and records WebKitGTK/GTK/GLib/session versions;
5. verifies hostile HTTP/HTTPS/file/data/javascript navigation, `window.open`, and download denial in the real WebView;
6. verifies no Docker/PostgreSQL/Node process, listening localhost socket, root requirement, or mandatory system/user service is needed at runtime.

A01b originally named that materialization step **A01c**, and A01c later called the remaining host step **A01d**. Those labels are retained only as provenance. DELIVERY-A01-003 subsequently allowed dependent source work to proceed with host evidence explicitly pending; A02 now exists. Starting with A02b, `tools/uts_verify.py` + `tools/uts_plan.json` are the canonical evolving host-verification mechanism. A01 remains partially implemented until the required build/runtime evidence actually passes.
