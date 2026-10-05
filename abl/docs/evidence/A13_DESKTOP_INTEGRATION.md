# A13 — Linux desktop lifecycle/integration capability detection

## Status

Implemented at source/deterministic-check level. Canonical Cargo/frontend/runtime UTS remains the acceptance gate.

## Boundary

A13 adds Linux-session integration without changing planner/schema/sync semantics:

- detects Wayland/X11 from sanitized session environment without exposing raw display/socket values to WebView;
- probes the existing session D-Bus for `org.freedesktop.Notifications`, `org.kde.StatusNotifierWatcher` and `org.freedesktop.portal.Desktop` without starting services;
- exposes only capability states through typed Tauri IPC;
- keeps tray lifecycle disabled and installs/enables no systemd user service;
- adds a strict `p2pkanban://activate|workspace/<uuid>|board/<uuid>|card/<uuid>` grammar;
- reuses the A06 mode-0600 XDG runtime Unix datagram for second-instance deep-link routing;
- preserves `activate-main-v1` unchanged and adds a bounded `deep-link-v1` payload only after application validation;
- queues accepted deep-link intents in native memory and lets the UI drain them through a typed command.

No generic WebView D-Bus, shell, filesystem, URL-handler registration or tray API is introduced. Package-level `.desktop` scheme registration remains A15 packaging work. File-open/import association remains later integration work.

## Lifecycle decision

ADR-006 remains unchanged: normal close means process exit. A13 only detects whether a StatusNotifier host exists; it does not create a tray icon or close-to-tray lifecycle. Missing notification/tray/portal services are supported degraded states and do not affect local planner correctness.

## Deep-link security

Deep links are accepted only when:

- the scheme is exactly `p2pkanban`;
- the target is one of `activate`, `workspace`, `board`, `card`;
- entity targets contain a canonical lowercase hyphenated UUID;
- no query, fragment, percent escape, control character or extra path segment is present;
- the URL is at most 512 bytes;
- the activation datagram is at most 1024 bytes.

The single-instance socket remains private to the user runtime directory and writer ownership is still enforced independently by the A06 profile lock.

## Tests / acceptance

Deterministic A13 checks cover the capability/application boundary, strict deep-link parser/codec, bounded in-memory queue, A06 socket reuse, typed IPC, absence of tray/systemd enablement and UTS wiring.

Canonical UTS adds:

- `cargo test ... a13_`;
- `tools/a13_host_integration_probe.py`, which runs only the built binary against isolated XDG roots, proves no-session-D-Bus degradation, malformed-link rejection and second-instance validated deep-link routing;
- manual KDE Plasma Wayland, GNOME Wayland and one X11 session checks for actual notification/StatusNotifier/portal availability behavior.

## Explicit non-claims

A13 does not claim notification delivery UX, visible tray behavior, custom scheme registration by a package, portable-bundle file association, close-to-tray, background sync while the process is closed, or a systemd user daemon. Those require later product/packaging evidence rather than hidden lifecycle expansion.
