# A02 — explicit web ↔ desktop transport boundary

## FACT

The current web implementation centralizes HTTP behavior in `frontend/src/shared/api/client.ts`; existing feature callers such as system/version call `apiRequest('/health')`. The architecture baseline requires this presentation-facing seam to remain practical while desktop replaces HTTP with typed in-process IPC.

The A02 source now contains:

- `src/shared/api/client.ts` — presentation-facing `apiRequest` facade;
- `src/shared/transport/web.ts` — explicit HTTP adapter for web/coordinator deployments;
- `src/shared/transport/desktop.ts` — desktop adapter using only `@tauri-apps/api/core::invoke`;
- `src-tauri/src/desktop_api.rs` — first application-shaped Rust command (`desktop_api_health`);
- an explicit desktop route table containing only `GET /health`; unknown routes fail closed;
- no localhost fallback, arbitrary command name, filesystem/process/network plugin, or generic WebView privilege.

`@tauri-apps/api` is pinned to 2.11.1. Tauri documents `invoke` in `@tauri-apps/api/core`; the package has no runtime dependencies and belongs to the same Tauri 2.11 line as the selected Rust runtime.

## INFERENCE

Keeping `apiRequest<T>(path, init)` at the presentation boundary lets web-origin feature modules move incrementally without preserving HTTP as the desktop architecture. Each desktop route must be mapped explicitly to an application-shaped Rust command. This is deliberately more restrictive than forwarding arbitrary URL/method/body triples to Rust.

## PROPOSAL

A03 should introduce the Rust application/domain service boundary behind these commands. New desktop routes should call application services, not repositories/SQL directly. Auth/token lifecycle is intentionally deferred to A07 so A02 does not introduce a premature secret model.

## UNRESOLVED EXPERIMENT / UTS EVIDENCE

The patch-construction environment cannot install the locked npm package set or compile/run Tauri. `docs/UTS_VERIFICATION.md` and `tools/uts_plan.json` now own the host verification sequence. The first UTS build passed frontend checks and Cargo dependency preparation but exposed the missing-icon defect recorded in `A02B_UTS_BUILD_FINDINGS.md`; A02b fixes it. Post-fix native build and WebView→Rust IPC evidence remain pending.
