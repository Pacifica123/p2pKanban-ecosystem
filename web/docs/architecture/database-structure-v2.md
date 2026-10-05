# Database structure v2

- Статус: Draft v1
- Дата: 2026-04-01
- Назначение: зафиксировать **конечную data model v2** для first migrations MVP и sync-ready foundation.

> Этот документ сужает и конкретизирует прежний `docs/architecture/database.md` под реальную первую волну миграций. Он исходит из уже принятого MVP: `workspace / board / column / card`, `labels`, `checklists`, `comments`, минимальная коллаборация, local-first web UX и backend-coordinated sync foundation. Первая волна миграций сознательно включала только `audit_log`, а минимальный user-facing activity slice теперь фиксируется как следующий шаг поверх этой базы; attachments, custom fields, integrations и full p2p по-прежнему не входят.

## 1. Базовые решения

### 1.1. СУБД
Для v1 принимается **PostgreSQL**.

Почему:
- удобные partial indexes;
- `jsonb` для sync/audit payload;
- надежные FK и transactional migrations;
- понятная эволюция к более сложному sync-слою.

### 1.2. ID
Все sync-visible и domain-visible сущности получают **UUIDv7**, генерируемый приложением.

БД не считается источником UUID по умолчанию. Это упрощает local-first создание объектов до синхронизации.

### 1.3. Время
Используем `timestamptz`.

Разводим три типа времени:
- `created_at` — время появления строки в серверной проекции;
- `updated_at` — время последнего изменения серверной проекции;
- `occurred_at` в `change_events` — клиентское/репличное время события, если оно было передано.

### 1.4. Projection-first + sync-aware
Основные domain tables хранят **текущее победившее состояние** сущностей.

Отдельно храним:
- `change_events` — технический журнал изменений;
- `tombstones` — технический факт удаления;
- `sync_cursors` — прогресс синхронизации реплик;
- `audit_log` — технический аудит server-side действий.

Это **не полный event sourcing**. Проекция остается основной моделью чтения.

## 2. Soft delete и tombstones

### 2.1. Решение
Для sync-visible сущностей принимается модель:
- в projection-таблице есть `deleted_at`;
- для удаления дополнительно создается запись в `tombstones`.

### 2.2. Почему не только `deleted_at`
Одного `deleted_at` недостаточно для sync-задач:
- нужен отдельный переносимый факт удаления;
- нужно защищаться от "воскрешения" старой репликой;
- позже нужен controlled purge / compaction.

### 2.3. Почему не только tombstone
Одного tombstone тоже недостаточно:
- projection-слою нужен быстрый признак того, что строка не активна;
- soft deleted сущность может временно понадобиться для диагностики, восстановления, конфликтов и GC.

### 2.4. Какие таблицы soft-delete
`deleted_at` обязателен для:
- `users`
- `devices` (опционально, но в v1 оставляем)
- `workspaces`
- `workspace_members`
- `boards`
- `board_columns`
- `cards`
- `board_labels`
- `card_labels`
- `checklists`
- `checklist_items`
- `comments`

`user_sessions` soft delete не требует — там достаточно `revoked_at` и `expires_at`.

## 3. Таблицы v1

Ниже — **обязательный first-migrations slice**.

---

## 3.1. Identity / auth

### users
Назначение:
- учетная запись пользователя.

Поля:
- `id uuid pk`
- `email text not null`
- `username text null`
- `display_name text not null`
- `password_hash text null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Индексы и ограничения:
- unique active email: `lower(email)` where `deleted_at is null`
- unique active username: `lower(username)` where `username is not null and deleted_at is null`

### devices
Назначение:
- зарегистрированное устройство/клиентский install context пользователя.

Поля:
- `id uuid pk`
- `user_id uuid not null fk -> users`
- `display_name text not null`
- `platform text not null`
- `public_key text null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `last_seen_at timestamptz null`
- `revoked_at timestamptz null`
- `deleted_at timestamptz null`

Индексы:
- `(user_id)` active
- `(user_id, last_seen_at desc)`

### user_sessions
Назначение:
- web-session / refresh-token слой.

Поля:
- `id uuid pk`
- `user_id uuid not null fk -> users`
- `device_id uuid null fk -> devices`
- `refresh_token_hash text not null`
- `user_agent text null`
- `ip_address inet null`
- `created_at timestamptz not null`
- `last_seen_at timestamptz null`
- `expires_at timestamptz not null`
- `revoked_at timestamptz null`

Индексы:
- `(user_id, expires_at)`
- partial unique по `refresh_token_hash` для неотозванных сессий

---

## 3.2. Workspace / access

### workspaces
Поля:
- `id uuid pk`
- `name text not null`
- `slug text null`
- `description text null`
- `owner_user_id uuid not null fk -> users`
- `visibility text not null default 'private'`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `archived_at timestamptz null`
- `deleted_at timestamptz null`

Ограничения:
- `visibility in ('private','shared','public_readonly')`
- для v1 сервисный слой использует фактически `private|shared`; `public_readonly` оставляется как future-ready значение

Индексы:
- unique active slug: `lower(slug)` where `slug is not null and deleted_at is null`
- `(owner_user_id, created_at desc)`

### workspace_members
Поля:
- `id uuid pk`
- `workspace_id uuid not null fk -> workspaces`
- `user_id uuid not null fk -> users`
- `role text not null`
- `invited_by_user_id uuid null fk -> users`
- `joined_at timestamptz not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deactivated_at timestamptz null`
- `deleted_at timestamptz null`

Ограничения:
- `role in ('owner','admin','member','viewer')`
- одна активная membership-запись на `(workspace_id, user_id)`
- не более одной активной owner-membership на workspace

Индексы:
- unique active `(workspace_id, user_id)` where `deactivated_at is null and deleted_at is null`
- `(user_id, joined_at desc)`
- `(workspace_id, role)` active

---

## 3.3. Boards

### boards
Поля:
- `id uuid pk`
- `workspace_id uuid not null fk -> workspaces`
- `name text not null`
- `description text null`
- `board_type text not null default 'kanban'`
- `created_by_user_id uuid null fk -> users`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `archived_at timestamptz null`
- `deleted_at timestamptz null`

Индексы:
- `(workspace_id, created_at desc)` active
- `(workspace_id, archived_at)`

### board_columns
Поля:
- `id uuid pk`
- `board_id uuid not null fk -> boards`
- `name text not null`
- `description text null`
- `position numeric(20,10) not null`
- `color_token text null`
- `wip_limit integer null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Ограничения:
- `wip_limit is null or wip_limit >= 0`
- normalized column name unique inside active board

Индексы:
- unique active `(board_id, lower(btrim(name)))`
- `(board_id, position, id)` active
- unique `(board_id, id)` для composite FK из `cards`

---

## 3.4. Cards and labels

### cards
Поля:
- `id uuid pk`
- `board_id uuid not null fk -> boards`
- `column_id uuid not null`
- `parent_card_id uuid null`
- `title text not null`
- `description text null`
- `position numeric(20,10) not null`
- `priority text null`
- `start_at timestamptz null`
- `due_at timestamptz null`
- `created_by_user_id uuid null fk -> users`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Ограничения:
- `priority is null or priority in ('low','medium','high','urgent')`
- `due_at is null or start_at is null or due_at >= start_at`
- `(board_id, column_id)` должен ссылаться на колонку той же доски
- `(board_id, parent_card_id)` должен ссылаться на карточку той же доски

Индексы:
- `(board_id, column_id, position, id)` active
- `(board_id, updated_at desc)` active
- `(board_id, due_at)` active
- unique `(board_id, id)` для downstream composite FK

Состояние карточки определяется только `column_id`. Фиксированного card-status
enum и отдельной даты завершения в domain/API нет. Миграция beta.11 также
физически удаляет из `cards` прежние колонки `status` и `completed_at`, чтобы в
хранилище не оставалось второго, конкурирующего определения состояния.

### board_labels
Поля:
- `id uuid pk`
- `board_id uuid not null fk -> boards`
- `name text not null`
- `color text not null`
- `description text null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Ограничения:
- normalized label name unique inside active board

Индексы:
- unique active `(board_id, lower(btrim(name)))`
- unique `(board_id, id)` для composite FK из `card_labels`

### card_labels
Назначение:
- sync-visible relation таблица, поэтому она **не hard-delete-only**.

Поля:
- `id uuid pk`
- `board_id uuid not null`
- `card_id uuid not null`
- `label_id uuid not null`
- `created_at timestamptz not null`
- `deleted_at timestamptz null`

Ограничения:
- `(board_id, card_id)` -> `cards(board_id, id)`
- `(board_id, label_id)` -> `board_labels(board_id, id)`
- одна активная связь `(card_id, label_id)`

Индексы:
- unique active `(card_id, label_id)` where `deleted_at is null`
- `(board_id, card_id)` active
- `(board_id, label_id)` active

---

## 3.5. Rich card content

### checklists
Поля:
- `id uuid pk`
- `card_id uuid not null fk -> cards`
- `title text not null`
- `position numeric(20,10) not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Индексы:
- `(card_id, position, id)` active

### checklist_items
Поля:
- `id uuid pk`
- `checklist_id uuid not null fk -> checklists`
- `title text not null`
- `is_done boolean not null default false`
- `position numeric(20,10) not null`
- `due_at timestamptz null`
- `completed_at timestamptz null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Ограничения:
- если `is_done = true`, то `completed_at` должен быть not null
- если `is_done = false`, то `completed_at` должен быть null

Индексы:
- `(checklist_id, position, id)` active
- `(checklist_id, is_done)` active

### comments
Поля:
- `id uuid pk`
- `card_id uuid not null fk -> cards`
- `author_user_id uuid null fk -> users`
- `body text not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz null`

Индексы:
- `(card_id, created_at, id)` active
- `(author_user_id, created_at desc)`

---

## 3.6. Sync foundation

### replicas
Назначение:
- логический источник изменений.

Поля:
- `id uuid pk`
- `user_id uuid null fk -> users`
- `device_id uuid null fk -> devices`
- `replica_kind text not null default 'client'`
- `client_instance_key text null`
- `display_name text null`
- `platform text null`
- `protocol_version text null`
- `app_version text null`
- `created_at timestamptz not null`
- `last_seen_at timestamptz null`
- `revoked_at timestamptz null`

Ограничения:
- `replica_kind in ('client','server','import')`
- при наличии `device_id` допустимо иметь несколько реплик на устройство, но `client_instance_key` должен быть уникален в пределах устройства, если он передан

Индексы:
- unique `(device_id, client_instance_key)` where `device_id is not null and client_instance_key is not null`
- `(user_id, created_at desc)`
- `(last_seen_at desc)`

### change_events
Назначение:
- технический журнал нормализованных изменений.

Поля:
- `id uuid pk`
- `server_order bigint generated always as identity`
- `workspace_id uuid null fk -> workspaces`
- `replica_id uuid not null fk -> replicas`
- `device_id uuid null fk -> devices`
- `actor_user_id uuid null fk -> users`
- `entity_type text not null`
- `entity_id uuid not null`
- `operation text not null`
- `field_mask text[] not null default '{}'`
- `payload_jsonb jsonb not null default '{}'::jsonb`
- `metadata_jsonb jsonb not null default '{}'::jsonb`
- `lamport bigint not null`
- `replica_seq bigint not null`
- `base_server_order bigint null`
- `occurred_at timestamptz null`
- `received_at timestamptz not null`
- `applied_at timestamptz null`
- `status text not null default 'applied'`
- `rejection_code text null`
- `correlation_id uuid null`
- `causation_id uuid null`

Ограничения:
- unique `(replica_id, replica_seq)`
- unique `(server_order)`
- `operation in ('create','update','delete','restore','reorder','add','remove','archive','unarchive')`
- `status in ('accepted','applied','duplicate','rejected','conflict')`
- `lamport > 0`
- `replica_seq > 0`

Индексы:
- `(workspace_id, server_order)`
- `(entity_type, entity_id, server_order desc)`
- `(replica_id, replica_seq)`
- `(status, received_at desc)`
- GIN по `payload_jsonb` допустим, но не обязателен в first migration

### sync_cursors
Назначение:
- хранение прогресса replica -> coordinator по прочитанному серверному stream.

Поля:
- `id uuid pk`
- `replica_id uuid not null fk -> replicas`
- `cursor_scope text not null`
- `scope_id uuid null`
- `last_server_order bigint not null default 0`
- `last_event_received_at timestamptz null`
- `updated_at timestamptz not null`

Ограничения:
- отдельный unique index для `global` cursor на `(replica_id, cursor_scope)`
- отдельный unique index для `workspace` cursor на `(replica_id, cursor_scope, scope_id)`
- `cursor_scope in ('global','workspace')`
- если `cursor_scope = 'global'`, то `scope_id is null`
- если `cursor_scope = 'workspace'`, то `scope_id is not null`

Индексы:
- `(replica_id, updated_at desc)`
- `(cursor_scope, scope_id)`

### tombstones
Назначение:
- sync-технический факт удаления.

Поля:
- `id uuid pk`
- `workspace_id uuid null fk -> workspaces`
- `entity_type text not null`
- `entity_id uuid not null`
- `delete_event_id uuid null fk -> change_events`
- `deleted_by_user_id uuid null fk -> users`
- `deleted_by_replica_id uuid null fk -> replicas`
- `deleted_at timestamptz not null`
- `purge_after_at timestamptz null`
- `metadata_jsonb jsonb not null default '{}'::jsonb`

Ограничения:
- unique `(entity_type, entity_id)`

Индексы:
- `(workspace_id, deleted_at desc)`
- `(purge_after_at)` where `purge_after_at is not null`

---

## 3.7. Audit / activity

### audit_log
Назначение:
- технический server-side аудит.

Это **не user-facing activity center**. Для MVP этого достаточно.

Поля:
- `id uuid pk`
- `workspace_id uuid null fk -> workspaces`
- `actor_user_id uuid null fk -> users`
- `actor_device_id uuid null fk -> devices`
- `actor_replica_id uuid null fk -> replicas`
- `action_type text not null`
- `target_entity_type text null`
- `target_entity_id uuid null`
- `request_id uuid null`
- `metadata_jsonb jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null`

Индексы:
- `(workspace_id, created_at desc)`
- `(target_entity_type, target_entity_id, created_at desc)`
- `(actor_user_id, created_at desc)`

### activity_entries
После этапа Activity / history / audit фиксируем минимальную read-model таблицу:
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
- `created_at timestamptz not null`

Индексы:
- `(workspace_id, created_at desc)`
- `(board_id, created_at desc, id desc)`
- `(card_id, created_at desc, id desc)` where `card_id is not null`
- `(actor_user_id, created_at desc)` where `actor_user_id is not null`
- `(kind, created_at desc)`

Назначение:
- отдельная read model для board/card history;
- user-facing слой поверх доменных изменений;
- не замена `change_events` и не замена `audit_log`.

### Почему это отдельная таблица, а не прямое чтение из `change_events`
Потому что user-facing history:
- требует noise suppression;
- требует board/card-scoped semantics;
- требует snapshots, удобные для UI;
- не должна показывать rejected/duplicate/conflict технические записи.

## 4. Связи и правила ссылочной целостности

### 4.1. Workspace ownership
- `workspaces.owner_user_id -> users.id`
- удаление owner hard-delete'ом не рассматривается как обычный путь; в projection используем soft delete

### 4.2. Board / column / card consistency
- `boards.workspace_id -> workspaces.id`
- `board_columns.board_id -> boards.id`
- `cards.board_id -> boards.id`
- `cards(board_id, column_id) -> board_columns(board_id, id)`
- `cards(board_id, parent_card_id) -> cards(board_id, id)`

Это важно: карточка не может указывать на колонку или parent card из другой доски.

### 4.3. Labels consistency
`card_labels` хранит `board_id`, чтобы SQL-уровнем гарантировать:
- card и label принадлежат одной board;
- invalid cross-board связь не сможет пройти даже при баге сервисного слоя.

### 4.4. Column delete policy
Физическое удаление колонки не является обычной операцией. При soft delete policy сервиса должна сначала:
- переместить карточки в другую колонку;
- или отклонить удаление непустой колонки.

На уровне FK для active projection используем `ON DELETE RESTRICT`.

## 5. Индексная стратегия

### 5.1. Partial active indexes
Почти все пользовательские list/query сценарии должны работать через partial indexes по активным строкам:
- `where deleted_at is null`
- иногда еще `and archived_at is null`

Это уменьшает шум от soft deleted данных.

### 5.2. Позиционные индексы
Для ordered сущностей:
- `board_columns(board_id, position, id)`
- `cards(board_id, column_id, position, id)`
- `checklists(card_id, position, id)`
- `checklist_items(checklist_id, position, id)`

### 5.3. Sync indexes
Критичны:
- `change_events(replica_id, replica_seq)`
- `change_events(workspace_id, server_order)`
- `change_events(entity_type, entity_id, server_order desc)`
- `sync_cursors(replica_id, cursor_scope, scope_id)`
- `tombstones(entity_type, entity_id)`

## 6. Что оставляем за пределами first migrations

Не входят в current SQL draft:
- `workspace_invitations`
- `board_views`
- `board_filter_presets`
- `attachments`
- `custom_fields`
- `card_custom_field_values`
- `integration_*`
- compaction / GC scheduler tables

## 7. Итоговое решение

Для v1 окончательно фиксируем такую логику:
- **projection tables** для core domain;
- **soft delete + tombstone** для sync-visible удаления;
- **change_events** как технический журнал, но не как полный event sourcing;
- **audit_log** как минимальный серверный аудит;
- **activity_entries** как отдельную user-facing read model поверх domain hooks и sync/audit foundation;
- migration-слой остается projection-first и не превращается в full event sourcing.


## Appearance / customization additions

### `user_appearance_preferences`
Персональные UI-настройки пользователя.

Ключевые поля:
- `user_id` PK/FK -> `users.id`
- `app_theme`
- `density`
- `reduce_motion`
- `created_at`
- `updated_at`

### `board_appearance_settings`
Shared-настройки отображения доски.

Ключевые поля:
- `board_id` PK/FK -> `boards.id`
- `theme_preset`
- `wallpaper_kind`
- `wallpaper_value`
- `column_density`
- `card_preview_mode`
- `show_card_description`
- `show_card_dates`
- `show_checklist_progress`
- `custom_properties_jsonb`
- `created_at`
- `updated_at`

Ключевой принцип: preset ids и lightweight config хранятся в БД, но не полный theme registry и не файловые ассеты.
