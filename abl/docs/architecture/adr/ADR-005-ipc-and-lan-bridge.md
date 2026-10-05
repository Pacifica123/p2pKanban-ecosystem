# ADR-005 — Arch IPC and optional LAN compatibility bridge

**Status:** accepted; implemented through A14
**Decision:** typed Tauri IPC is the normal UI/core boundary. No localhost HTTP API is opened by default. A narrowly scoped authenticated LAN bridge may exist only as an explicit short-lived migration/pairing compatibility feature.

## Grounds
- [FACT] Existing React feature access is centralized enough to substitute a transport adapter.
- [FACT] Current node/device migration paths may temporarily benefit from HTTP/LAN compatibility.
- [INFERENCE] Permanent HTTP preserves avoidable CSRF/CORS/Host/port/firewall lifecycle and adds wakeups/exposure.

## Rejected alternatives
- always-on `127.0.0.1` Axum server;
- always-on LAN service/mDNS discovery;
- arbitrary one-command-per-UI-component Tauri bridge without a versioned application command layer;
- automatic firewall/polkit modification.

## Costs
Typed DTO/application command layer and an additional bounded compatibility adapter until newer device-link flows remove it.

## Failure modes
Bridge remains open; weak one-time token; hostile LAN peer; origin/host confusion; oversized import; UI gains generic filesystem/network power.

## Verification
Normal-mode socket scan; TTL/auto-close; random capability; endpoint/size/rate tests; hostile-LAN and malformed request suite; prove zero firewall changes; IPC schema fuzz and remote-navigation tests.
