# Migrations plan v1

- Статус: Draft v1
- Дата: 2026-04-01
- Цель: разложить first migrations на понятные, обратимые и проверяемые шаги.

## Общий принцип

1. Сначала создаем справочные функции и техбазу.
2. Затем identity/auth.
3. Потом core domain.
4. Потом sync foundation.
5. Потом audit.

Каждая миграция должна быть:
- транзакционной;
- с явными индексами;
- без смешивания unrelated bounded contexts;
- без premature future-ready таблиц.

## Предлагаемая последовательность

### 0001_base.sql
Содержимое:
- helper function `set_row_updated_at()`;
- общие комментарии/конвенции;
- при необходимости расширения уровня PostgreSQL (`pgcrypto` не обязателен, если UUIDv7 всегда генерирует приложение).

Почему первой:
- все следующие таблицы используют одинаковую стратегию `updated_at`.

### 0002_identity_and_auth.sql
Таблицы:
- `users`
- `devices`
- `user_sessions`

Что проверяем после миграции:
- уникальность email/username на active user;
- ревокация устройств и сессий;
- связь user -> device -> session.

### 0003_workspaces.sql
Таблицы:
- `workspaces`
- `workspace_members`

Что проверяем:
- owner и membership роли;
- одна активная membership на пользователя внутри workspace;
- slug uniqueness среди активных workspace.

### 0004_boards.sql
Таблицы:
- `boards`
- `board_columns`

Что проверяем:
- board belongs to workspace;
- unique normalized column names внутри доски;
- reorder колонок по `position`.

### 0005_cards_and_labels.sql
Таблицы:
- `cards`
- `board_labels`
- `card_labels`

Что проверяем:
- card не может ссылаться на колонку другой доски;
- parent_card не может выйти за пределы board;
- label-binding не может соединять card и label из разных board;
- soft delete связи `card_labels` не ломает повторное назначение label.

### 0006_checklists_and_comments.sql
Таблицы:
- `checklists`
- `checklist_items`
- `comments`

Что проверяем:
- reorder checklist и checklist_items;
- completed-state для checklist_item;
- soft delete comments.

### 0007_sync_foundation.sql
Таблицы:
- `replicas`
- `change_events`
- `sync_cursors`
- `tombstones`

Что проверяем:
- unique `(replica_id, replica_seq)`;
- monotonic `server_order`;
- курсор global/workspace;
- tombstone uniqueness по `(entity_type, entity_id)`.

### 0008_audit_log.sql
Таблица:
- `audit_log`

Что проверяем:
- привязку аудита к actor/request/target;
- фильтрацию по workspace/actor/target.

### 0009_seed_reference_data.sql
Необязательная миграция.

Содержимое:
- опциональные seed-значения или технические comments on table/column;
- базовые server-side board type/priority conventions, если решим фиксировать их reference-данными, а не только check constraints; состояние карточки всегда задаёт пользовательская колонка.

## Что сознательно не делаем в первой волне

Не включаем:
- future-ready таблицы;
- materialized views для activity;
- отдельный compaction job storage;
- миграции под integrations;
- board appearance и кастомизацию;
- custom fields.

## Рекомендации по rollout

### На локальной разработке
Последовательность:
1. поднимаем чистую БД;
2. применяем все миграции;
3. прогоняем smoke insert/select/update/delete для каждого bounded context;
4. отдельно прогоняем sync acceptance tests.

### На staging
Нужно проверить:
- размер и планы выполнения на list-эндпоинтах;
- повторный прием одного `change_event`;
- tombstone priority над устаревшим update;
- удаление column/card/comment и поведение read-model.

## Что должно появиться сразу после migrations plan

Следующий инженерный шаг после этих миграций:
- repo-слой под каждую таблицу;
- сервисы, которые транслируют CRUD в change-aware mutations;
- первые интеграционные тесты на `boards`, `cards`, `sync`.


## 0006_appearance_and_customization.sql

Добавляет минимальный customization slice поверх core MVP:
- `user_appearance_preferences`
- `board_appearance_settings`

Почему отдельной миграцией:
- customization появляется после core CRUD и не должна смешиваться с базовой board/card моделью;
- это облегчает откат и проверку реального влияния customization на backend;
- migration отделяет shared board appearance от будущих assets/theme registry решений.
