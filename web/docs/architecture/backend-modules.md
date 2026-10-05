# Карта backend-модулей

- Статус: справочная карта реализованного модульного монолита
- Дата актуализации: 2026-07-25
- Назначение: зафиксировать ownership и границы backend-модулей.

> Фактический состав файлов имеет приоритет. Auth, appearance, activity, audit,
> labels, checklists, comments, sync и transport outbox уже реализованы;
> integrations остаются частичными.

---

## 1. Принципы декомпозиции

### 1.1. Один модуль = одна зона ответственности
Модуль группируется не по таблицам и не по HTTP-файлам, а по устойчивой прикладной ответственности.

Примеры:
- `boards` владеет не только `boards`, но и `board_columns`, потому что колонка не имеет самостоятельной жизни вне доски;
- `workspaces` владеет и `workspace_members`, потому что membership — это часть доступа к workspace;
- `cards` владеет базовой карточкой, но не комментариями и не чек-листами как отдельными поддоменами.

### 1.2. Aggregate-root ownership важнее таблиц
Владение определяется root-сущностью:
- `workspace` → модуль `workspaces`
- `board` → модуль `boards`
- `card` → модуль `cards`

Подчиненные сущности не обязаны получать отдельный физический модуль, если их жизненный цикл полностью связан с root.

### 1.3. Зависимости идут сверху вниз
Допустимая форма зависимости:
- `handler -> service -> repo`
- модуль приложения может зависеть от публичного сервиса другого модуля
- repo одного модуля не должен напрямую дергать repo другого модуля

Запрещаем:
- `handler -> чужой repo`
- `repo -> service`
- круговые зависимости между application modules

### 1.4. Sync и audit — cross-cutting, но не “god modules”
`sync` и `audit` видят несколько доменных модулей, но не должны поглощать бизнес-логику workspaces/boards/cards.

---

## 2. Модули, которые реально создаем в v1

Ниже — **физические backend-модули**, которые стоит завести уже в backend skeleton.

### 2.1. Core / required in v1
- `auth`
- `users`
- `workspaces`
- `boards`
- `cards`
- `labels`
- `checklists`
- `comments`
- `appearance`
- `activity`
- `sync`
- `integrations`

### 2.2. Infra / shared
- `common`
- `db`
- `http`
- `config`
- `state`
- `error`
- `audit` как infra-support модуль или `common/audit`

### 2.3. Future-ready, но не обязательные для full runtime wiring v1
- `attachments`
- `custom_fields`
- `invitations`

`integrations` на этом этапе уже создается физически как stub-модуль с provider registry и adapter contracts, но без production-ready provider execution.

---

## 3. Responsibility map

## 3.1. auth

**Отвечает за:**
- login / logout / refresh;
- выпуск и отзыв сессий;
- password-based authentication для MVP;
- связку `user_sessions` + `devices` при web/login flow;
- извлечение authenticated principal из запроса.

**Не отвечает за:**
- профиль пользователя;
- membership и workspace access;
- бизнес-операции домена.

**Таблицы:**
- `user_sessions`
- частично `devices` в части auth/session lifecycle

**Основные операции:**
- sign in;
- sign out current session;
- sign out all sessions;
- refresh token;
- get current auth session.

## 3.2. users

**Отвечает за:**
- профиль пользователя;
- self profile (`me`);
- устройства пользователя как пользовательский surface;
- минимальные user preferences, если они понадобятся до отдельного settings-модуля.

**Не отвечает за:**
- выдачу токенов;
- workspace membership;
- board/card access rules.

**Таблицы:**
- `users`
- частично `devices` как профиль устройства

**Основные операции:**
- read/update current user profile;
- list devices;
- revoke device;
- read public-safe user snapshot для membership/comments.

## 3.3. workspaces

**Отвечает за:**
- workspace CRUD;
- workspace membership;
- access checks на уровне workspace;
- workspace settings первого этапа;
- приглашения как внутренняя функция до появления отдельного `invitations`.

**Таблицы:**
- `workspaces`
- `workspace_members`

**Основные операции:**
- create workspace;
- list my workspaces;
- update/archive workspace;
- add/remove/deactivate member;
- change member role;
- resolve user access to workspace.

## 3.4. boards

**Отвечает за:**
- board CRUD;
- columns CRUD;
- reorder columns;
- board-level queries для board screen;
- board existence and board access check.

**Таблицы:**
- `boards`
- `board_columns`

**Основные операции:**
- create/update/archive board;
- list boards in workspace;
- create/update/delete column;
- reorder columns;
- get board with column projection.

## 3.5. cards

**Отвечает за:**
- card CRUD;
- move card между колонками;
- reorder cards внутри колонки;
- parent/subtask link внутри той же board;
- базовую card detail projection.

**Таблицы:**
- `cards`

**Основные операции:**
- create card in column;
- update card fields;
- move card;
- reorder cards;
- complete/cancel/restore card;
- read card detail.

## 3.6. labels

**Отвечает за:**
- board labels;
- card-label bindings;
- label validation в рамках board.

**Таблицы:**
- `board_labels`
- `card_labels`

**Основные операции:**
- create/update/delete label;
- attach label to card;
- detach label from card;
- list labels for board.

## 3.7. checklists

**Отвечает за:**
- checklist CRUD;
- checklist item CRUD;
- reorder checklist items;
- toggle done/undone.

**Таблицы:**
- `checklists`
- `checklist_items`

**Основные операции:**
- create checklist;
- rename/delete checklist;
- create/update/delete item;
- reorder items;
- mark item done/undone.

## 3.8. comments

**Отвечает за:**
- comments CRUD;
- author/edit/delete rules;
- card comment timeline.

**Таблицы:**
- `comments`

**Основные операции:**
- add comment;
- edit own comment;
- delete own/admin-visible comment;
- list card comments.


## 3.9. appearance

**Отвечает за:**
- персональные user appearance preferences;
- board appearance settings;
- валидацию wallpaper/theme preset shape;
- future-ready границу для workspace defaults и theme registry.

**Таблицы:**
- `user_appearance_preferences`
- `board_appearance_settings`

**Основные операции:**
- get/update current user appearance preferences;
- get/update board appearance settings.

## 3.10. integrations

**Отвечает за:**
- provider registry;
- import/export orchestration contracts;
- portable export / backup / restore-preview contracts;
- inbound/outbound webhook boundaries;
- translation between external payloads and normalized integration commands;
- isolation of GitHub/Obsidian/provider-specific DTOs from core domain modules.

**Не отвечает за:**
- core board/card/workspace business rules;
- canonical sync stream ownership;
- direct writes в domain tables в обход application services.

**Таблицы:**
- на текущем этапе обязательных таблиц нет;
- future-ready: provider_connections, integration_jobs, webhook_subscriptions, delivery_attempts.

**Основные операции:**
- list provider manifests;
- read provider detail;
- create import/export stub jobs;
- expose dedicated import/export capabilities, export and restore-preview endpoints;
- receive inbound webhook at reserved boundary.

**Замечание:**
`integrations` может зависеть от public service boundary других модулей, но не должен тащить их repo к себе и не должен заставлять core domain знать про внешний provider format. Для import/export/backup это означает отдельный orchestration surface поверх stable bundle contract, а не ad-hoc SQL dump endpoint.

## 3.11. sync

**Отвечает за:**
- replica registration/update;
- ingest normalized change envelopes;
- read incremental server stream;
- sync cursor management;
- tombstone lifecycle;
- idempotency on `(replica_id, replica_seq)`;
- orchestration применения изменений к доменным модулям.

**Таблицы:**
- `replicas`
- `change_events`
- `sync_cursors`
- `tombstones`

**Основные операции:**
- register replica;
- push changes;
- pull changes;
- advance cursor;
- reject/duplicate/conflict bookkeeping;
- optional snapshot manifest later.

## 3.12. activity

**Отвечает за:**
- user-facing history для `boards` и `cards`;
- чтение `activity_entries`;
- cursor pagination и filters по history feed;
- преобразование domain events/hooks в activity read model.

**Таблица:**
- `activity_entries`

**Ownership HTTP routes:**
- `GET /boards/{boardId}/activity`
- `GET /cards/{cardId}/activity`

**Замечание:**
`activity` не владеет бизнес-логикой `boards/cards/comments/checklists`; он владеет только read model и history-query surface.

## 3.13. audit

**Отвечает за:**
- технический server-side аудит;
- запись audit events из middleware и из domain services;
- correlation/request tracing на уровне backend.

**Таблица:**
- `audit_log`

**Замечание:**
`audit` и `activity` — разные модули. `audit` не надо смешивать с экраном пользовательской истории.

---

## 4. Где проходят границы ответственности

## 4.1. Почему `workspace_members` не отдельный модуль
Membership не существует без workspace и участвует в access rules того же workspace. Отдельный модуль дал бы лишние cross-module вызовы без реальной выгоды.

## 4.2. Почему `board_columns` внутри `boards`
Колонка не живет сама по себе: ее создание, удаление, позиционирование и ограничения полностью board-scoped.

## 4.3. Почему `labels` отдельно от `cards`
Хотя labels используются карточками, у label есть собственный lifecycle внутри доски, свои правила уникальности и свой API surface. Отдельный модуль несложен и снижает раздутие `cards`.

## 4.4. Почему `checklists` и `comments` отдельно от `cards`
На первом этапе их можно было бы спрятать внутрь `cards`, но они быстро разрастаются в отдельные use-cases, DTO и endpoints. Лучше сразу отделить их как поддомены карточки.

## 4.5. Почему `sync` не должен напрямую писать в чужие repo
Если `sync` начинает знать физические детали всех таблиц, он становится вторым backend внутри backend. Правильнее, чтобы `sync` вызывал публичные application-level handlers/traits вроде `apply_external_change_*` или специализированные mutators модулей.

---

## 5. Зависимости между модулями

Ниже — **разрешенные логические зависимости**.

```text
auth ------> users
   \           \
    \           -> workspaces
     \                \
      -> sync          -> boards -> labels
           \                 \        \
            \                 -> cards -> checklists
             \                           -> comments
              -> audit
```

### 5.1. Таблица зависимостей

| Модуль | Может зависеть от | Не должен зависеть от |
|---|---|---|
| `auth` | `users`, `common`, `db`, `audit` | `boards`, `cards`, `labels`, `checklists`, `comments` |
| `users` | `common`, `db`, `audit` | `boards`, `cards`, `sync` |
| `workspaces` | `users`, `common`, `db`, `audit` | `boards`, `cards`, `comments`, `sync` repo internals |
| `boards` | `workspaces`, `common`, `db`, `audit` | `cards`, `comments`, `sync` repo internals |
| `cards` | `boards`, `workspaces`, `common`, `db`, `audit` | `labels`, `checklists`, `comments` repos |
| `labels` | `boards`, `cards` (read-only validation port), `common`, `db`, `audit` | `checklists`, `comments`, `sync` repo internals |
| `checklists` | `cards`, `common`, `db`, `audit` | `labels`, `comments`, `sync` repo internals |
| `comments` | `cards`, `users`, `common`, `db`, `audit` | `labels`, `checklists`, `sync` repo internals |
| `sync` | публичные application ports всех sync-visible модулей, `common`, `db`, `audit` | прямые cross-module repo calls как основной путь |
| `activity` | `boards`, `cards`, `comments`, `checklists`, `labels`, `common`, `db`, `audit` | прямой ownership бизнес-логики workspaces/boards/cards/comments |
| `audit` | `common`, `db` | доменные модули как hard dependency |

### 5.2. Практическое правило
Если модулю нужен только факт существования чужой сущности или access check, он должен зависеть от **сервиса/порта**, а не от таблицы и не от repo другого модуля.

Примеры:
- `cards` спрашивает у `boards`, существует ли board и доступна ли колонка;
- `labels` спрашивает у `cards`, принадлежит ли card нужной board;
- `comments` спрашивает у `cards`, доступна ли card для comment action.

---

## 6. DTO / handler / service / repo по модулям

Ниже — рекомендуемый минимальный состав для skeleton и первой волны CRUD.

## 6.1. auth

### dto
- `sign_in_request`
- `sign_in_response`
- `refresh_session_request`
- `refresh_session_response`
- `current_session_response`

### handler
- `post_sign_in`
- `post_refresh`
- `post_sign_out`
- `post_sign_out_all`
- `get_current_session`

### service
- `auth_service`
- `session_service`
- `password_service`
- `token_service`

### repo
- `user_session_repo`
- `auth_user_repo` (read model for login)
- `device_auth_repo`

## 6.2. users

### dto
- `me_response`
- `update_me_request`
- `device_response`
- `list_devices_response`

### handler
- `get_me`
- `patch_me`
- `get_my_devices`
- `post_revoke_device`

### service
- `user_profile_service`
- `device_service`

### repo
- `user_repo`
- `device_repo`

## 6.3. workspaces

### dto
- `create_workspace_request`
- `workspace_response`
- `workspace_summary_response`
- `update_workspace_request`
- `list_workspaces_response`
- `add_member_request`
- `member_response`
- `update_member_role_request`

### handler
- `post_workspace`
- `get_workspaces`
- `get_workspace`
- `patch_workspace`
- `post_archive_workspace`
- `get_workspace_members`
- `post_workspace_member`
- `patch_workspace_member`
- `delete_workspace_member`

### service
- `workspace_service`
- `workspace_member_service`
- `workspace_access_service`

### repo
- `workspace_repo`
- `workspace_member_repo`
- `workspace_query_repo`

## 6.4. boards

### dto
- `create_board_request`
- `board_response`
- `board_summary_response`
- `update_board_request`
- `create_column_request`
- `column_response`
- `update_column_request`
- `reorder_columns_request`
- `board_detail_response`

### handler
- `post_board`
- `get_boards`
- `get_board`
- `patch_board`
- `post_archive_board`
- `get_board_columns`
- `post_board_column`
- `patch_board_column`
- `delete_board_column`
- `post_reorder_columns`

### service
- `board_service`
- `column_service`
- `board_access_service`
- `board_query_service`

### repo
- `board_repo`
- `column_repo`
- `board_query_repo`

## 6.5. cards

### dto
- `create_card_request`
- `card_response`
- `card_summary_response`
- `update_card_request`
- `move_card_request`
- `reorder_cards_request`
- `card_detail_response`

### handler
- `post_card`
- `get_cards`
- `get_card`
- `patch_card`
- `post_move_card`
- `post_reorder_cards`
- `post_complete_card`
- `post_restore_card`
- `delete_card`

### service
- `card_service`
- `card_move_service`
- `card_query_service`

### repo
- `card_repo`
- `card_query_repo`

## 6.6. labels

### dto
- `create_label_request`
- `update_label_request`
- `label_response`
- `attach_label_request`

### handler
- `get_board_labels`
- `post_board_label`
- `patch_board_label`
- `delete_board_label`
- `post_attach_label_to_card`
- `delete_detach_label_from_card`

### service
- `label_service`
- `card_label_service`

### repo
- `board_label_repo`
- `card_label_repo`

## 6.7. checklists

### dto
- `create_checklist_request`
- `update_checklist_request`
- `checklist_response`
- `create_checklist_item_request`
- `update_checklist_item_request`
- `checklist_item_response`
- `reorder_checklist_items_request`

### handler
- `get_card_checklists`
- `post_card_checklist`
- `patch_checklist`
- `delete_checklist`
- `post_checklist_item`
- `patch_checklist_item`
- `delete_checklist_item`
- `post_reorder_checklist_items`

### service
- `checklist_service`
- `checklist_item_service`

### repo
- `checklist_repo`
- `checklist_item_repo`

## 6.8. comments

### dto
- `create_comment_request`
- `update_comment_request`
- `comment_response`
- `list_comments_response`

### handler
- `get_card_comments`
- `post_card_comment`
- `patch_comment`
- `delete_comment`

### service
- `comment_service`
- `comment_policy_service`

### repo
- `comment_repo`

## 6.9. sync

### dto
- `register_replica_request`
- `register_replica_response`
- `push_changes_request`
- `push_changes_response`
- `pull_changes_request`
- `pull_changes_response`
- `sync_cursor_response`

### handler
- `post_register_replica`
- `post_push_changes`
- `get_pull_changes` or `post_pull_changes`
- `get_sync_status`

### service
- `replica_service`
- `sync_ingest_service`
- `sync_stream_service`
- `sync_cursor_service`
- `tombstone_service`
- `change_apply_service`

### repo
- `replica_repo`
- `change_event_repo`
- `sync_cursor_repo`
- `tombstone_repo`

## 6.10. activity

### dto
- `activity_entry_response`
- `activity_list_response`

### handler
- `get_board_activity`
- `get_card_activity`

### service
- `board_activity_service`
- `card_activity_service`
- `activity_projection_service`

### repo
- `activity_entry_repo`

## 6.11. audit

### service
- `audit_service`
- `request_audit_service`

### repo
- `audit_log_repo`

---

## 7. Маршрутизация по модулям

Ниже — рекомендованный ownership HTTP routes.

## 7.1. auth routes
```text
POST   /api/v1/auth/sign-in
POST   /api/v1/auth/refresh
POST   /api/v1/auth/sign-out
POST   /api/v1/auth/sign-out-all
GET    /api/v1/auth/session
```

## 7.2. users routes
```text
GET    /api/v1/me
PATCH  /api/v1/me
GET    /api/v1/me/devices
POST   /api/v1/me/devices/{deviceId}/revoke
```

## 7.3. workspaces routes
```text
GET    /api/v1/workspaces
POST   /api/v1/workspaces
GET    /api/v1/workspaces/{workspaceId}
PATCH  /api/v1/workspaces/{workspaceId}
POST   /api/v1/workspaces/{workspaceId}/archive
GET    /api/v1/workspaces/{workspaceId}/members
POST   /api/v1/workspaces/{workspaceId}/members
PATCH  /api/v1/workspaces/{workspaceId}/members/{memberId}
DELETE /api/v1/workspaces/{workspaceId}/members/{memberId}
```

## 7.4. boards routes
```text
GET    /api/v1/workspaces/{workspaceId}/boards
POST   /api/v1/workspaces/{workspaceId}/boards
GET    /api/v1/boards/{boardId}
PATCH  /api/v1/boards/{boardId}
POST   /api/v1/boards/{boardId}/archive
GET    /api/v1/boards/{boardId}/columns
POST   /api/v1/boards/{boardId}/columns
PATCH  /api/v1/boards/{boardId}/columns/{columnId}
DELETE /api/v1/boards/{boardId}/columns/{columnId}
POST   /api/v1/boards/{boardId}/columns/reorder
```

## 7.5. cards routes
```text
GET    /api/v1/boards/{boardId}/cards
POST   /api/v1/boards/{boardId}/cards
GET    /api/v1/cards/{cardId}
PATCH  /api/v1/cards/{cardId}
DELETE /api/v1/cards/{cardId}
POST   /api/v1/cards/{cardId}/move
POST   /api/v1/columns/{columnId}/cards/reorder
POST   /api/v1/cards/{cardId}/complete
POST   /api/v1/cards/{cardId}/restore
```

## 7.6. labels routes
```text
GET    /api/v1/boards/{boardId}/labels
POST   /api/v1/boards/{boardId}/labels
PATCH  /api/v1/boards/{boardId}/labels/{labelId}
DELETE /api/v1/boards/{boardId}/labels/{labelId}
POST   /api/v1/cards/{cardId}/labels
DELETE /api/v1/cards/{cardId}/labels/{labelId}
```

## 7.7. checklists routes
```text
GET    /api/v1/cards/{cardId}/checklists
POST   /api/v1/cards/{cardId}/checklists
PATCH  /api/v1/checklists/{checklistId}
DELETE /api/v1/checklists/{checklistId}
POST   /api/v1/checklists/{checklistId}/items
PATCH  /api/v1/checklists/items/{itemId}
DELETE /api/v1/checklists/items/{itemId}
POST   /api/v1/checklists/{checklistId}/items/reorder
```

## 7.8. comments routes
```text
GET    /api/v1/cards/{cardId}/comments
POST   /api/v1/cards/{cardId}/comments
PATCH  /api/v1/comments/{commentId}
DELETE /api/v1/comments/{commentId}
```

## 7.9. appearance routes
```text
GET    /api/v1/me/appearance
PUT    /api/v1/me/appearance
GET    /api/v1/boards/{boardId}/appearance
PUT    /api/v1/boards/{boardId}/appearance
```

## 7.10. activity routes
```text
GET    /api/v1/boards/{boardId}/activity
GET    /api/v1/cards/{cardId}/activity
```

## 7.11. sync routes
```text
POST   /api/v1/sync/replicas
POST   /api/v1/sync/push
POST   /api/v1/sync/pull
GET    /api/v1/sync/status
```

## 7.12. audit routes
```text
GET    /api/v1/workspaces/{workspaceId}/audit-log
```

### Правило маршрутизации
- route принадлежит модулю, который владеет primary action;
- nested path допустим даже при отдельном модуле, если root-контекст важен для UX и прав;
- read-heavy board screen можно потом собрать отдельным query endpoint, но ownership все равно должен остаться понятным.

---

## 8. App composition plan

## 8.1. Верхний уровень
Рекомендуемая композиция backend:

```text
main.rs
  -> config::load()
  -> db::connect()
  -> build repositories
  -> build services per module
  -> build AppState
  -> http::build_router(state)
  -> run server
```

## 8.2. AppState
`AppState` должен содержать:
- config;
- db pool / transaction factory;
- auth services;
- users services;
- workspaces services;
- boards services;
- cards services;
- labels services;
- checklists services;
- comments services;
- appearance services;
- activity services;
- sync services;
- audit service;
- clock / id generator / request context helpers.

### Важное правило
В `AppState` кладем **сервисы и порты**, а не сырые repo другого модуля “на всякий случай”.

## 8.3. Сборка модулей
Лучше, чтобы каждый модуль имел функцию вида:

```text
pub fn module(state: AppState) -> Router
```

или

```text
pub fn routes() -> Router<AppState>
```

И отдельный builder/constructor для service graph:

```text
pub fn build_module(deps: ModuleDeps) -> ModuleServices
```

## 8.4. Предпочтительная схема зависимостей при сборке

```text
auth
users
workspaces(users)
boards(workspaces)
cards(boards, workspaces)
labels(boards, cards-read-port)
checklists(cards)
comments(cards, users-read-port)
sync(ports from all sync-visible modules)
audit
http(router over all modules)
```

## 8.5. Ports, которые стоит ввести сразу
Чтобы не скатиться в cross-module repo coupling, полезно сразу выделить несколько портов:
- `WorkspaceAccessPort`
- `BoardAccessPort`
- `CardAccessPort`
- `CardLookupPort`
- `UserLookupPort`
- `SyncApplyPort` на стороне sync-visible модулей

Это даст возможность сначала жить в монолите, а потом эволюционировать без болезненной перекройки.

---

## 9. Рекомендуемая физическая структура backend/src

```text
backend/src/
  app.rs
  config.rs
  error.rs
  lib.rs
  main.rs
  state.rs
  common/
    ids/
    time/
    paging/
    auth/
    audit/
  db/
    mod.rs
    pool.rs
    tx.rs
  http/
    mod.rs
    router.rs
    middleware/
      auth.rs
      request_id.rs
      logging.rs
  modules/
    auth/
      dto/
      handler/
      service/
      repo/
      mod.rs
    users/
      dto/
      handler/
      service/
      repo/
      mod.rs
    workspaces/
      dto/
      handler/
      service/
      repo/
      mod.rs
    boards/
      dto/
      handler/
      service/
      repo/
      mod.rs
    cards/
      dto/
      handler/
      service/
      repo/
      mod.rs
    labels/
      dto/
      handler/
      service/
      repo/
      mod.rs
    checklists/
      dto/
      handler/
      service/
      repo/
      mod.rs
    comments/
      dto/
      handler/
      service/
      repo/
      mod.rs
    sync/
      dto/
      handler/
      service/
      repo/
      ports/
      mod.rs
```

`audit` можно держать в `common/audit` либо как `modules/audit`, если логика начнет расти.

---

## 10. Что точно не стоит делать в skeleton v1

1. Не выносить `columns` в отдельный top-level модуль.
2. Не делать отдельный `memberships`-модуль.
3. Не смешивать `labels/checklists/comments` обратно в один огромный `cards`-модуль.
4. Не строить `sync` как прямой SQL-оркестратор поверх всех таблиц.
5. Не плодить query-service на каждый экран раньше времени.
6. Не заводить future-ready модули физически только ради красоты.

---

## 11. Итоговое решение

Для MVP и backend skeleton принимаем следующую **рабочую physical module map**:
- `auth`
- `users`
- `workspaces`
- `boards`
- `cards`
- `labels`
- `checklists`
- `comments`
- `appearance`
- `activity`
- `sync`
- `integrations`
- `audit` как infra-support

Внутренние ownership-границы:
- `workspaces` владеет `workspace_members`
- `boards` владеет `board_columns`
- `cards` владеет только базовой карточкой и card-state
- `labels`, `checklists`, `comments` остаются отдельными модулями карточного уровня
- `sync` работает через порты и application services, а не через прямое смешение repo всех модулей

Именно эта схема должна лечь в основу следующего шага: **backend skeleton + module folders + router registration + service wiring**.
