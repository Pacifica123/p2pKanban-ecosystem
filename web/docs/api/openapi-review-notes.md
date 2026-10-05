# OpenAPI v1 review notes

## Что было не так в исходном файле
- `openapi.yaml` был скорее skeleton, чем полный v1-контракт.
- Маршруты auth/sync расходились с уже зафиксированной module map.
- В теги были добавлены `labels`, `checklists`, `comments`, но CRUD для них почти отсутствовал.
- Были зашиты `appearance` и `integrations`, хотя они вынесены за пределы MVP v1.
- Для большинства операций не хватало request/response схем и единого error envelope.
- Не были нормально оформлены session/device/replica-aware auth flows.
- Пагинация, фильтрация и сортировка были либо отсутствующими, либо неявными.

## Что исправлено
- Выровнен набор маршрутов под module map:
  - `auth/sign-up`, `auth/sign-in`, `auth/refresh`, `auth/sign-out`, `auth/sign-out-all`, `auth/session`
  - `me`, `me/devices`, revoke device
  - `workspaces`, `workspace members`
  - `boards`, `columns`
  - `cards`, `move`, `complete`, `restore`, `reorder`
  - `labels`, `checklists`, `comments`
  - `sync/replicas`, `sync/push`, `sync/pull`, `sync/status`
- Убраны `appearance` и `integrations` из v1-спеки как не-MVP surface.
- Добавлен единый `ErrorResponse`.
- Добавлены схемы почти для всех request/response DTO.
- Для коллекций введен cursor-based pagination там, где он реально нужен.
- Для `columns` оставлен полный ordered snapshot без pagination.
- Для `cards` добавлены фильтры и сортировка.
- Для auth описаны `bearerAuth` и `refreshTokenCookie`.
- Для sync добавлены `Replica`, `SyncCursor`, push/pull request/response и batch results.

## Что осталось открытым
- `POST /workspaces/{workspaceId}/members` сейчас добавляет участника по `userId`.
  Для удобного UX почти наверняка позже понадобится либо user lookup endpoint,
  либо email/invite flow.
- Политика public sign-up помечена как deployment-level choice:
  self-hosted инстанс может держать `auth/sign-up`, а может выключить его.
- Спека синтаксически парсится и все внутренние `$ref` разрешаются,
  но полноценный внешний OpenAPI validator в этой среде я не запускал.


## Appearance / customization follow-up

После отдельного customization-этапа в v1 добавлены endpoints `GET/PUT /me/appearance` и `GET/PUT /boards/{boardId}/appearance`, а также соответствующие схемы для user preferences и board appearance settings. Image-wallpapers и theme registry по-прежнему остаются за пределами текущего API slice.

## Contract parity sweep follow-up

После sweep `openapi.yaml` выровнен по фактически смонтированным backend routes и текущим frontend API calls. Детальная матрица и статусы routes вынесены в `docs/api/contract-parity-sweep-v1.md`.

Ключевые решения:
- `labels/checklists/comments` не выдаются за готовый product surface: routes оставлены в OpenAPI как `deferred_stub` и должны возвращать `501 not_implemented` до minimal card enrichment slice;
- `sync` также остается `deferred_stub`; фактический backend route для pull сейчас `GET /sync/pull`;
- `integrations/import-export/webhooks` помечены как `contract_stub`: они дают стабильные capabilities/stub responses, но не являются настоящим execution layer;
- user/device naming приведен к backend: `DELETE /me/devices/{deviceId}` вместо несуществующего `POST /me/devices/{deviceId}/revoke`;
- убраны несуществующие OpenAPI paths вроде `PATCH /me`, `POST /boards/{boardId}/columns/reorder`, label attach/detach routes и checklist item reorder route;
- добавлен повторяемый guard: `python tools/contract_parity_sweep.py --check`.

Важная оговорка: backend wire-format для success responses остается `{ "data": ... }`, а frontend `apiRequest<T>` разворачивает этот envelope. Текущий OpenAPI по-прежнему описывает payload-level schema для `data`; перед генерацией клиента нужно либо явно формализовать envelope wrapper, либо генерировать envelope-aware client.
