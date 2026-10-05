# Структура базы данных

> Важно: этот документ фиксирует расширенную архитектурную карту БД, а не
> точный объем обязательной реализации для первого рабочего релиза. Продуктовые
> границы v1 зафиксированы в `docs/product/v1-execution-roadmap.md`, а
> фактическая схема — в `backend/migrations/`.
>
> Часть названных ниже future-ready таблиц уже реализована последующими
> миграциями: appearance, activity/audit и transport outbox. Поэтому этот файл
> нельзя использовать как список «ещё не сделано».

Документ фиксирует стартовую схему БД на уровне доменных таблиц. Это не SQL,
а архитектурная карта будущих миграций.

## MVP first migrations: обязательное ядро

### identity / auth
- users
- devices
- user_sessions / refresh_tokens

### workspace / access
- workspaces
- workspace_members

### boards / cards
- boards
- board_columns
- cards
- board_labels
- card_labels
- checklists
- checklist_items
- comments

### sync-ready foundation
- replicas
- change_events
- sync_cursors
- tombstones

## Future-ready таблицы

Ниже перечислены таблицы, которые **могут существовать в архитектуре**, но не
обязаны входить в first migrations MVP:
- workspace_invitations
- board_views
- board_filters_presets
- attachments
- custom_fields
- card_custom_field_values
- themes / wallpapers / board appearance
- integration_* таблицы
- activity_log как отдельный продуктовый слой

## Core identity

### users
Назначение:
- учетная запись пользователя.

Ключевые поля:
- id (uuid)
- email
- username
- display_name
- password_hash nullable
- created_at
- updated_at
- deleted_at

### devices
Назначение:
- зарегистрированные устройства пользователя.

Ключевые поля:
- id (uuid)
- user_id
- display_name
- platform
- public_key nullable
- created_at
- last_seen_at
- revoked_at

### user_sessions / refresh_tokens
Назначение:
- поддержка web-auth и обновления сессий.

## Workspace access

### workspaces
- id
- name
- slug
- description
- owner_user_id
- visibility
- created_at
- updated_at
- archived_at
- deleted_at

### workspace_members
- id
- workspace_id
- user_id
- role
- invited_by
- joined_at
- deactivated_at

### workspace_invitations
Future-ready таблица.
- id
- workspace_id
- email nullable
- invited_user_id nullable
- role
- token
- expires_at
- accepted_at
- revoked_at
- created_at

## Boards

### boards
- id
- workspace_id
- name
- description
- board_type
- is_archived или archived_at
- created_by
- created_at
- updated_at
- deleted_at

### board_columns
- id
- board_id
- name
- description
- position
- color_token
- wip_limit
- created_at
- updated_at
- deleted_at

### board_views
Future-ready таблица.
- id
- board_id
- name
- view_type
- config_json
- is_default
- created_at
- updated_at

### board_filters_presets
Future-ready таблица.
- id
- board_id
- name
- filter_json
- created_by
- created_at
- updated_at

## Cards

### cards
- id
- board_id
- column_id
- parent_card_id nullable
- title
- description
- position
- priority
- due_at
- start_at
- created_by
- created_at
- updated_at
- deleted_at

### board_labels
- id
- board_id
- name
- color
- description
- created_at
- updated_at
- deleted_at

### card_labels
- id
- card_id
- label_id
- created_at

## Rich card content

### checklists
- id
- card_id
- title
- position
- created_at
- updated_at
- deleted_at

### checklist_items
- id
- checklist_id
- title
- is_done
- position
- due_at
- completed_at
- created_at
- updated_at
- deleted_at

### comments
- id
- card_id
- author_user_id
- body
- created_at
- updated_at
- deleted_at

### attachments
Future-ready таблица.
- id
- card_id
- storage_kind
- storage_ref
- filename
- mime_type
- size_bytes
- uploaded_by
- created_at
- deleted_at

### custom_fields
Future-ready таблица.
- id
- board_id
- name
- field_type
- config_json
- position
- created_at
- updated_at
- deleted_at

### card_custom_field_values
Future-ready таблица.
- id
- card_id
- custom_field_id
- value_json
- updated_at
- deleted_at

## Sync infrastructure

### replicas
- id
- device_id nullable
- workspace_id nullable
- replica_kind
- protocol_version
- created_at
- last_sync_at
- revoked_at

### change_events
- id
- replica_id
- entity_type
- entity_id
- operation
- payload_json
- field_mask_json nullable
- logical_clock
- created_at
- received_at nullable

### sync_cursors
- id
- source_replica_id
- target_replica_id
- last_event_id nullable
- last_logical_clock nullable
- updated_at

### tombstones
- id
- entity_type
- entity_id
- deleted_by_replica_id
- deleted_at
- purge_after_at nullable
