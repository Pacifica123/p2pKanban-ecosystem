# A03 — Rust application/domain boundary

Status: **implemented at source + deterministic-contract level; Cargo compile/tests are delegated to the canonical UTS verifier**.

## Evidence classification

### Fact

The implementation anchor used by A00 shows that the current web backend composition root carries a PostgreSQL `PgPool` in `AppState`, while many repository/service paths accept `PgPool` or issue `sqlx` queries directly. The A03 architecture baseline explicitly requires that serious SQLite work must not begin by mechanically translating those PostgreSQL-shaped APIs.

Before A03, the Arch-native Tauri command `desktop_api_health` constructed the complete response itself. That made the command small, but there was not yet an executable application boundary behind IPC.

A02d UTS evidence already proves the native shell, frontend build, Cargo test/build and non-root Wayland launch probe on a Manjaro/Arch-like host. A03 therefore changes the Rust ownership boundary, not the process model.

### Inference

Keeping Tauri state/DTO mapping in `desktop_api.rs` while moving the use case into transport-agnostic `application/` code gives later web-compatible commands a stable composition pattern without importing Axum, PostgreSQL or SQLite assumptions. A small domain value layer is enough for this stage; inventing board repositories before A04 would make repository semantics speculative.

### Proposal implemented by A03

The native path is now:

`React → typed desktop transport → allowlisted Tauri command → ApplicationServices → SystemService → domain values`.

`src-tauri/src/application/**` owns application use cases/read models. `src-tauri/src/domain/**` owns platform-independent core values. `src-tauri/src/desktop_api.rs` is the platform adapter and owns the current IPC wire mapping. `main.rs` is the composition root and injects `ApplicationServices` into Tauri-managed state.

The existing `/health`-compatible wire result is intentionally unchanged: `status`, `service`, `version`, `env`. This proves the boundary without creating a second frontend migration.

Command DTO/error convention from this point forward:

- application/domain APIs never return Tauri, HTTP or SQL DTOs;
- platform adapters map application read models into their wire DTOs;
- fallible use cases introduced by later stages must expose typed application errors, with Tauri/HTTP error-envelope mapping kept in the adapter;
- stringly transport errors must not become domain errors;
- persistence errors must be translated at the repository/application boundary rather than leaking SQLite/PostgreSQL types upward.

### Unresolved experiment / deliberately not implemented

A03 does **not** introduce a repository trait, SQLite, XDG storage, board/card entities, network clients, background workers, secret persistence or a second local service. Those belong to A04+ and remain `planned`.

The current `domain/system.rs` values are only the minimal platform-independent core exercised by the health use case; they are not claimed to represent the Kanban business model. A04 must derive repository semantic contracts from existing web/Android fixtures before real board persistence ports begin.

## Verification

`tools/check_a03.py` rejects Tauri/Axum/SQL/HTTP/filesystem/process/network dependencies in `application/` and `domain/`, verifies the Tauri adapter delegates through `ApplicationServices`, rejects premature persistence dependencies in `Cargo.toml`, and requires Rust unit tests for domain/application/adapter mapping.

`tools/uts_plan.json` includes A03, so the existing one-command UTS flow also runs `cargo test --locked --offline` and `cargo build --locked --offline`. No separate manual command list is introduced.

Next exact architecture patch: **A04 — repository semantic contract suite**.
