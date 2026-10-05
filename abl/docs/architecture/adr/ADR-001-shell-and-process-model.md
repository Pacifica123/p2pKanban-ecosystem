# ADR-001 — Arch shell and process model

**Status:** accepted / implementation-driving; A01a source boundary + A01b/A01c acceptance contracts implemented; A02b fixes first UTS build defect; post-fix materialized runtime evidence pending  
**Decision:** Tauri 2 hosts the existing React/Vite UI using system WebKitGTK; privileged/application behavior lives in one in-process Rust core. No default localhost backend or system/user daemon.

## Grounds
- [FACT] Current UI is React/Vite and most calls pass through centralized `apiRequest`.
- [FACT] Backend plus sync/transport core are already Rust.
- [FACT] Tauri uses the Linux system WebKitGTK stack rather than shipping a private Chromium runtime.
- [FACT] Android demonstrates local-first state can be authoritative without a browser/server process pair.
- [INFERENCE] Reusing UI while moving authority to Rust removes Docker/runtime overhead without creating an expensive GTK/Qt parity rewrite.

## Rejected alternatives
- Electron: strongest web reuse but duplicated Chromium/Node footprint conflicts with laptop/idle goals.
- Full GTK/Qt rewrite: potentially more widget-native, but large parity risk before storage/sync contracts stabilize.
- Permanent Axum localhost process: preserves ports/CORS/CSRF/process supervision with little product value.
- Always-on systemd user daemon: adds idle/session-bus/keyring complexity and is not required for local-first correctness.

## Costs
WebKitGTK rolling-version testing; typed IPC adapter; Linux-specific lifecycle/desktop integration; renderer regressions may track distro updates.

## Failure modes
WebKitGTK regression/loader failure; Wayland-specific input/render issue; compromised WebView invokes over-broad IPC; hidden process remains after close.

## Verification
Clean Arch package install; Wayland+X11 E2E; no listening sockets in normal mode; remote navigation blocked; IPC fuzz/allowlist audit; aggregate process-tree memory/power benchmark; close/tray behavior under desktops with and without StatusNotifier host.
