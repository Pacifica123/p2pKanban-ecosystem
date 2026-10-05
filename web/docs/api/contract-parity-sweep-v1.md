# Contract parity sweep v1

Дата ревизии: 2026-05-18.

Цель sweep — убрать рассинхрон между тремя источниками правды:

- реально смонтированные backend routes в `backend/src/auth/mod.rs` и `backend/src/modules/*/mod.rs`;
- frontend API calls в `frontend/src/features/**/api/*.ts`;
- `docs/api/openapi.yaml`.

Проверка намеренно касается именно `METHOD path`. Схемы request/response остаются частью OpenAPI-review и smoke/integration проверок, но основные wire-оговорки после sweep зафиксированы ниже.

## Итог

`openapi.yaml` теперь отражает фактически смонтированный beta-surface:

- backend routes: 78 operations;
- frontend API calls: 43 operations;
- OpenAPI operations: 78 operations;
- frontend API calls являются подмножеством backend/OpenAPI;
- `/health` исключен из sweep, потому что это operational health endpoint, а не product API route.

Для защиты от повторного дрейфа добавлен lightweight check:

```bash
python tools/contract_parity_sweep.py --check
```

## Статусы routes

В `openapi.yaml` у операций добавлено поле `x-v1Status`.

| Статус | Смысл |
| --- | --- |
| `real_v1` | Реальный v1/beta route с рабочей backend-реализацией. |
| `internal_dev` | Dev-only route, который нужен локальной разработке, но не является production v1 API. |
| `internal_compat` | Реальный backend route, оставленный как совместимый/служебный вариант рядом с preferred frontend path. |
| `contract_stub` | Route возвращает устойчивый контрактный stub/manifest/capabilities, но не выполняет полноценную бизнес-операцию. |
| `deferred_stub` | Route смонтирован в backend, но текущая реализация возвращает `501 not_implemented`; это reserved surface для следующих v1-блоков. |

## Real v1 surface

Рабочим v1/beta surface сейчас считаются:

- auth/session: `sign-up`, `sign-in`, `refresh`, `sign-out`, `sign-out-all`, `session`;
- current user/device read/revoke: `GET /me`, `GET /me/devices`, `DELETE /me/devices/{deviceId}`;
- workspace CRUD/lifecycle and members;
- board CRUD/lifecycle;
- columns through preferred scoped frontend routes `PATCH/DELETE /boards/{boardId}/columns/{columnId}`;
- unscoped column routes `PATCH/DELETE /columns/{columnId}` как `internal_compat`;
- cards CRUD/lifecycle/move/reorder;
- appearance: `me/appearance`, `boards/{boardId}/appearance`;
- activity/audit: board activity, card activity, workspace audit log.
- minimal card enrichment: labels, checklists, checklist items, comments.
- sync baseline: replica registration/status, idempotent push, cursor pull.
- export/backup safety net: capabilities, real workspace/board JSON bundle export and non-destructive import preview.

## Deferred/internal surface

Следующие зоны остаются не готовыми как полноценные product routes:

- `integrations/import-export/imports`: execution endpoint remains non-destructive in v1 and returns `preview_required`; actual apply/import-as-copy mutation is future work.
- `integrations/webhooks`: это `contract_stub` surface. Он валидирует provider key и возвращает стабильный stub receipt, но пока не делает signature verification или webhook delivery.
- `POST /auth/dev-bootstrap`: `internal_dev` только для local/dev bootstrap.

## Что было исправлено в OpenAPI

- Убран несуществующий `PATCH /me`.
- `POST /me/devices/{deviceId}/revoke` заменен на фактический `DELETE /me/devices/{deviceId}`.
- Добавлены реальные `DELETE /workspaces/{workspaceId}` и `DELETE /boards/{boardId}`.
- Добавлены реальные unscoped `PATCH/DELETE /columns/{columnId}` и помечены `internal_compat`.
- Убран несуществующий `POST /boards/{boardId}/columns/reorder`.
- Labels выровнены под backend: `/labels/{labelId}` и `PUT /cards/{cardId}/labels`.
- Checklist item paths выровнены под backend: `/checklist-items/{itemId}`.
- Убран несуществующий checklist item reorder route.
- Sync выровнен под backend и переведен в `real_v1`: `GET/POST /sync/replicas`, `GET /sync/status`, `POST /sync/push`, `GET /sync/pull`.
- Import/export safety net переведен из manifest stub в реальный JSON bundle contract: `GET /integrations/import-export/capabilities`, `POST /integrations/import-export/exports`, `POST /integrations/import-export/imports/preview`.
- Добавлен `501 NotImplemented` response для оставшихся deferred/contract stubs.
- Error envelope schema выровнен с текущим backend: `error.code`, `error.message`, `error.details` без обязательного `requestId`.

## Frontend parity notes

Frontend API modules сейчас вызывают `labels/checklists/comments` для минимально полезной карточки и `sync/status/replicas/pull` для sync baseline. `sync/push` пока покрыт backend smoke/API level и остается не подключенным к local-first CRUD flush напрямую.

Две frontend API функции были уточнены по типам:

- `deleteColumn(...)` теперь типизируется как `BoardColumn`, потому что backend возвращает удаленную/soft-deleted column в `data` envelope;
- `deleteCard(...)` теперь типизируется как `Card`, потому что backend возвращает удаленную/soft-deleted card в `data` envelope.

## Wire-format caveat

Backend success responses физически оборачиваются в `ApiEnvelope<T>`:

```json
{ "data": { } }
```

Frontend `apiRequest<T>` это envelope разворачивает и дальше работает с `T`. Поэтому текущий OpenAPI по-прежнему описывает payload-level schema для `data`, а не генерирует отдельную envelope-схему на каждую operation. Для будущей генерации клиента это нужно будет либо формализовать через общий response-wrapper, либо явно генерировать envelope-aware client.

## Следующий практический блок

После sweep ближайший продуктовый блок остается прежним: `minimal card enrichment slice` — labels/checklists/comments надо переводить из `deferred_stub` в рабочий минимальный v1 slice.
