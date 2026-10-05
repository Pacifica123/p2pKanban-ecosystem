# p2p-planner backend

Текущая backend-часть — это Axum + sqlx + PostgreSQL сервис для core kanban flow,
appearance и activity/audit surface.

Transport evolution is staged beside the coordinator:

- `crates/sync-core` owns the transport-neutral event contract;
- optional Nostr shadow mirroring uses a durable outbox;
- `crates/iroh-transport` provides a native direct-path adapter;
- none of these adapters replaces backend authorization or PostgreSQL domain
  projections by default.

## Что уже заведено

- bootable HTTP server;
- config loading from `config/default.toml` + environment variables;
- PostgreSQL pool;
- startup migrations;
- app state + tracing + error envelope;
- modular router composition;
- core CRUD для `workspaces / boards / columns / cards`;
- appearance endpoints;
- activity / history / audit read-model endpoints.

## Запуск локально

1. Подними PostgreSQL и создай базу `p2p_planner`.
2. Проверь `.env`.
3. Запусти backend:

```bash
cargo run
```

Health endpoints:

- `GET /health`
- `GET /api/v1/health`

## Auth / session model

Основной API-flow сейчас идет через `Authorization: Bearer ...`: frontend получает access token на `/auth/sign-in`, `/auth/sign-up` или `/auth/refresh`, а refresh token хранится в cookie. Protected endpoints должны извлекать пользователя из bearer-сессии.

Legacy `X-User-Id` fallback оставлен только для dev/test сценариев и выключен по умолчанию через `AUTH__ENABLE_DEV_HEADER_AUTH=false`. Его не нужно считать нормальным browser flow и не нужно возвращать в CORS без отдельного решения.

Для beta/self-host/production-like профилей backend теперь валидирует security env на старте: `X-User-Id` не попадает в CORS headers без local/dev header-auth режима, wildcard CORS запрещен, `AUTH__COOKIE_SECURE=true` обязателен, а `AUTH__JWT_SECRET` должен быть реальным non-default секретом.

## Smoke tests

- `tests/core_crud_smoke.rs`
- `tests/appearance_smoke.rs`
- `tests/smoke_core_api.py`

Integration tests требуют `TEST_DATABASE_URL` или `DATABASE_URL`.

## Experimental transport checks

Runtime configuration and the relay-only recovery gate are documented in
`../docs/deployment/free-hosting-transports-v1.md`.

Queue diagnostics:

```text
GET /api/v1/sync/transports/status
```

Relay recovery:

```bash
cargo run --bin nostr_recover -- <workspace-uuid> ../recovered-events.json
```
