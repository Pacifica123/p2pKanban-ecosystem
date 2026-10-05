# Activity / history / audit v1

- Статус: Draft v1
- Дата: 2026-04-02
- Назначение: развести **sync change log**, **технический audit** и **user-facing history** так, чтобы проект не скатился ни в full event sourcing, ни в "магическую" историю, собранную из случайных следов.

> Этот документ опирается на уже принятые решения: projection-first data model, `change_events` как sync-технический журнал, `audit_log` как server-side аудит, local-first web UX и modular monolith backend. Здесь мы добавляем **минимальный продуктовый history slice** для `boards` и `cards`, но не открываем отдельный большой activity center.

## 1. Три разных слоя, которые нельзя смешивать

### 1.1. `change_events`
Это **технический sync-журнал**.

Он нужен для:
- реплик;
- курсоров;
- идемпотентности;
- конфликтов;
- tombstone-aware удаления.

`change_events`:
- может содержать rejected/duplicate/conflict записи;
- хранит sync payload, а не UX-представление;
- не должен считаться готовым пользовательским экраном истории.

### 1.2. `audit_log`
Это **технический server-side аудит**.

Он нужен для:
- диагностики backend-поведения;
- security/admin trace;
- request/correlation tracking;
- ответа на вопрос "какой authenticated actor и какой server-side action выполнил запрос".

`audit_log`:
- не обязан быть удобным для обычного пользователя;
- может включать auth/session/device события;
- должен быть доступен ограниченному кругу ролей.

### 1.3. `activity_entries`
Это **user-facing projection** для истории изменений.

Он нужен для:
- карточки: показать, кто и что менял;
- доски: показать недавние значимые действия;
- восстановления контекста совместной работы.

`activity_entries`:
- не являются источником истины по данным;
- пишутся только после успешного прикладного изменения;
- содержат структурированный payload для UI, а не сырой sync/event payload.

## 2. Что считаем целью v1

В рамках этого этапа принимаем **ограниченный, но реальный** activity/history slice:
- история для `board`;
- история для `card`;
- workspace-level технический `audit_log`;
- без отдельного глобального activity center;
- без full replay всех промежуточных local попыток;
- без тяжелого diff engine для rich text.

Иными словами:
- `board` получает **операционный recent activity feed**;
- `card` получает **детальную timeline-историю**;
- `workspace` получает **admin/technical audit log**.

## 3. Главные правила записи истории

### 3.1. Пишем только после успешного applied изменения
User-facing activity создается только тогда, когда доменная операция реально принята и применена.

Не пишем activity для:
- failed validation;
- rejected sync event;
- duplicate sync event;
- optimistic local attempt, который не был принят сервером;
- read-only запросов.

### 3.2. История — append-only projection, а не canonical storage
Текущее состояние сущности читается из projection-таблиц.

`activity_entries` нужны для объяснения изменений, а не для восстановления всей domain-модели. Если activity временно отсутствует, это не ломает источник истины.

### 3.3. Не логируем технический шум как пользовательскую историю
В user-facing history **не попадают**:
- refresh token rotation;
- sign-in / sign-out;
- `sync_cursors` updates;
- heartbeat / replica last seen;
- auto-updated timestamps без смыслового изменения;
- rejected/duplicate/conflict bookkeeping.

Для этого есть `audit_log` и `change_events`.

### 3.4. История хранит структурированные данные, не готовые локализованные строки
Сервер отдает:
- `kind`;
- `fieldMask`;
- `payload`;
- `actor`;
- `createdAt`.

Человекочитаемый текст собирается на клиенте. Это упрощает локализацию и не цементирует UI-тексты в БД.

## 4. Какие экраны и какие границы истории

## 4.1. История доски
История доски — это **не полный журнал всего, что когда-либо происходило внутри каждой карточки**.

В v1 она показывает:
- lifecycle самой доски;
- изменения колонок;
- создание карточек;
- перемещение карточек между колонками;
- архивирование / восстановление / удаление карточек.

В v1 она **не показывает** как отдельные feed items:
- каждое редактирование описания карточки;
- каждый comment внутри карточки;
- каждое изменение checklist item;
- reorder карточек внутри той же колонки.

Причина: иначе board feed превращается в шумный поток, а не в useful обзор.

## 4.2. История карточки
История карточки — это **детальная timeline** по конкретной card и ее дочерним объектам.

В v1 она показывает:
- создание карточки;
- изменение основных полей карточки;
- перемещение между колонками;
- completion / reopen;
- archive / restore / delete;
- attach/detach label;
- create/update/delete checklist;
- create/update/complete/reopen/delete checklist item;
- create/update/delete comment.

## 4.3. Audit log workspace
`audit_log` — это отдельный admin/technical surface.

Он отвечает на вопросы вроде:
- кто вошел в систему;
- кто обновил board settings;
- кто дернул admin-чувствительный endpoint;
- какой request трогал конкретную сущность.

Это **не** основной пользовательский экран истории.

## 5. Каталог activity-событий v1

## 5.1. Board history event kinds
### Board-level
- `board.created`
- `board.updated`
- `board.archived`
- `board.restored`
- `board.deleted`

### Column-level
- `column.created`
- `column.updated`
- `column.deleted`
- `column.reordered`

### Card-level, видимые в board feed
- `card.created`
- `card.moved`
- `card.archived`
- `card.restored`
- `card.deleted`

## 5.2. Card history event kinds
### Card-level
- `card.created`
- `card.updated`
- `card.moved`
- `card.archived`
- `card.restored`
- `card.deleted`

### Labels
- `label.attached`
- `label.detached`

### Checklists
- `checklist.created`
- `checklist.updated`
- `checklist.deleted`

### Checklist items
- `checklist_item.created`
- `checklist_item.updated`
- `checklist_item.completed`
- `checklist_item.reopened`
- `checklist_item.deleted`

### Comments
- `comment.created`
- `comment.updated`
- `comment.deleted`

## 5.3. Какие поля изменения считаем значимыми для `card.updated`
В `fieldMask` и `payload` для `card.updated` в v1 имеет смысл выводить только прикладно значимые поля:
- `title`
- `description`
- `priority`
- `startAt`
- `dueAt`

Переход между пользовательскими состояниями фиксируется отдельным
`card.moved` через изменение `columnId`; card-status enum отсутствует.
Исторические записи прежних beta с kind `card.completed`/`card.reopened`
клиент может прочитать как нейтральное «карточка изменена», но новые события
таких видов не создаются и в board feed не входят.

Технические поля вроде `updatedAt` в history не выводим.

## 5.4. Антишум-политика
В v1 принимаем такие правила:
- reorder карточек **внутри той же колонки** не попадает в user-facing history;
- bulk reorder колонок пишет **одну** запись `column.reordered` на запрос;
- многоfield update карточки пишет **одну** запись `card.updated` с `fieldMask`, а не по событию на поле;
- server-side batch action может быть сгруппирован одним `requestId`.

## 6. Data model для минимальной user-facing истории

## 6.1. Таблица `activity_entries`
Предлагаемая read-model таблица:
- `id uuid pk`
- `workspace_id uuid not null fk -> workspaces`
- `board_id uuid not null fk -> boards`
- `card_id uuid null fk -> cards`
- `actor_user_id uuid null fk -> users`
- `kind text not null`
- `entity_type text not null`
- `entity_id uuid not null`
- `field_mask text[] not null default '{}'`
- `payload_jsonb jsonb not null default '{}'::jsonb`
- `request_id uuid null`
- `source_change_event_id uuid null fk -> change_events`
- `source_audit_log_id uuid null fk -> audit_log`
- `created_at timestamptz not null default now()`

### Комментарии по полям
`board_id` обязателен, потому что и board history, и card history живут внутри board-scoped UX.

`card_id`:
- `null` для board-level и column-level activity;
- заполнен для card-level activity и дочерних card-событий.

`payload_jsonb` хранит именно UI-полезные snapshots, например:
- `cardTitle`;
- `boardName`;
- `columnName`;
- `fromColumn` / `toColumn`;
- `changes` с `before/after` только для значимых полей.

## 6.2. Ограничения и индексы
Минимально нужны:
- индекс `(workspace_id, created_at desc)`
- индекс `(board_id, created_at desc, id desc)`
- индекс `(card_id, created_at desc, id desc)` where `card_id is not null`
- индекс `(actor_user_id, created_at desc)` where `actor_user_id is not null`
- индекс `(kind, created_at desc)`

## 6.3. Почему отдельная таблица лучше, чем читать историю напрямую из `change_events`
Потому что `change_events`:
- слишком sync-ориентирован;
- содержит лишние для UI состояния;
- не обязан хранить snapshots, удобные для показа;
- плохо подходит для noise suppression и board/card feed semantics.

`activity_entries` — это нормальная read model, а не попытка сделать UI из технического лога.

## 7. Activity endpoints v1

## 7.1. Board activity
`GET /boards/{boardId}/activity`

Query params:
- `limit` — `1..100`, default `50`
- `cursor` — opaque cursor для пагинации назад по времени
- `kinds[]` — optional filter по типам событий
- `actorUserId` — optional filter

Ответ:
- reverse chronological order;
- cursor pagination;
- только события, видимые пользователю с read-access к board.

## 7.2. Card history
`GET /cards/{cardId}/activity`

Query params:
- `limit` — `1..100`, default `50`
- `cursor` — opaque cursor
- `kinds[]` — optional filter

Ответ:
- reverse chronological order;
- timeline по card и ее дочерним сущностям;
- read access к card наследуется от board/workspace access rules.

## 7.3. Workspace audit log
`GET /workspaces/{workspaceId}/audit-log`

Query params:
- `limit` — `1..200`, default `100`
- `cursor` — opaque cursor
- `actionType` — optional filter
- `actorUserId` — optional filter
- `targetEntityType` — optional filter
- `targetEntityId` — optional filter

Доступ:
- только `owner/admin` workspace;
- не для обычного board/card UX.

## 7.4. Почему write endpoints не нужны
`activity_entries` и `audit_log` создаются автоматически domain services и middleware.

Отдельные `POST /activity` или `POST /audit-log` в публичном API не нужны.

## 8. Response shape

## 8.1. `ActivityEntryResponse`
Минимальная форма:
- `id`
- `createdAt`
- `kind`
- `workspaceId`
- `boardId`
- `cardId nullable`
- `entityType`
- `entityId`
- `actor`
  - `userId nullable`
  - `displayName nullable`
- `fieldMask[]`
- `payload`
- `requestId nullable`

## 8.2. `ActivityListResponse`
- `items: ActivityEntryResponse[]`
- `nextCursor: string | null`

## 8.3. `AuditLogEntryResponse`
Минимальная форма:
- `id`
- `createdAt`
- `actionType`
- `workspaceId nullable`
- `actorUserId nullable`
- `targetEntityType nullable`
- `targetEntityId nullable`
- `requestId nullable`
- `metadata`

## 9. Права доступа

### Board activity
Доступна всем, кто может читать board.

### Card activity
Доступна всем, кто может читать соответствующую card.

### Workspace audit log
Доступен только `owner/admin`.

Важно: даже если actor позже удален или деактивирован, старая activity-запись сохраняется. UI должен уметь показывать fallback вроде `Unknown user`.

## 10. Где и как это строится в backend

### 10.1. Кто пишет `activity_entries`
Писать activity должен не middleware, а **domain/application слой** после успешной бизнес-операции.

Причина:
- middleware знает слишком мало о доменном смысле;
- только доменный слой знает, было ли это meaningful change;
- именно доменный слой знает field mask, from/to column и другие UI-полезные данные.

### 10.2. Кто пишет `audit_log`
`audit_log` может писаться:
- из middleware для request/auth/session событий;
- из domain services для чувствительных server-side действий.

### 10.3. Граница модулей
Логично разделить:
- `audit` — infra-support модуль;
- `activity` — read-model / user-history модуль.

При этом `activity` не должен становиться owner бизнес-логики `boards` или `cards`; он только получает доменно осмысленные записи после успешного изменения.

## 11. Что сознательно не берем в этот этап

Не берем:
- отдельный глобальный `/activity` центр на весь workspace;
- full-text search по истории;
- pin/bookmark activity items;
- subscriptions/notifications на activity;
- compliance-grade immutable audit vault;
- rich diff rendering для больших текстов;
- генерацию history напрямую из `change_events` без read model.

## 12. Итоговое решение в одной фразе

В проекте фиксируются **три разные сущности изменений**:
- `change_events` — sync-техника,
- `audit_log` — server-side аудит,
- `activity_entries` — user-facing история,

а продуктовый минимум этого этапа — это **board activity + card history + workspace audit log**, без превращения всей системы в full event sourcing или отдельный аналитический центр.
