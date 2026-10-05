# Доменная модель: сущности

> Важно: этот документ описывает целевую доменную модель и future-proof основу.
> Наличие сущности здесь не означает автоматическое включение в первую рабочую
> версию. Актуальный продуктовый срез см. в `docs/product/mvp-scope-v1.md`, а
> канонические трактовки терминов — в `docs/domain/terms.md`.

## Карта зрелости сущностей

### Обязательные продуктовые сущности v1
- Workspace
- WorkspaceMember
- Board
- BoardColumn
- Card
- BoardLabel
- CardLabel
- Checklist
- ChecklistItem
- Comment
- UserAppearancePreferences
- BoardAppearanceSettings
- ActivityEntry

### Обязательная инфраструктурная основа v1
- User
- Device
- Replica
- ChangeEvent / SyncCursor / Tombstone как sync-ready внутренняя модель
- AuditLog как server-side технический журнал

### Future-ready, но не обязательные для MVP
- WorkspaceInvitation
- Attachment
- CustomField
- CardCustomFieldValue
- Theme catalog / theme registry
- Wallpaper asset
- IntegrationProvider
- IntegrationConnection
- IntegrationLink
- WorkspaceInvitation UI flows beyond minimal membership

## 1. Workspace

Логическая верхнеуровневая область данных. Workspace объединяет:
- участников;
- доски;
- настройки;
- правила доступа;
- в будущем — интеграции и расширенные workspace-level настройки.

### Основные поля
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

## 2. WorkspaceMember

Связь пользователя с workspace.

### Основные поля
- id
- workspace_id
- user_id
- role
- joined_at
- invited_by
- deactivated_at

### Базовые роли
- owner
- admin
- member
- viewer

## 3. WorkspaceInvitation

Future-ready сущность для приглашения пользователя в workspace.
В MVP как отдельная пользовательская фича не обязательна.

### Основные поля
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

## 4. Board

Доска Kanban внутри workspace.

### Основные поля
- id
- workspace_id
- name
- description
- board_type
- is_archived / archived_at по выбранной модели хранения
- created_by
- created_at
- updated_at
- deleted_at

## 5. BoardColumn

Колонка внутри конкретной доски.

### Основные поля
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

### Комментарий
Количество колонок не фиксировано. Система должна поддерживать
произвольное число колонок и их перестановку.

## 6. Card

Карточка задачи или объекта учета.

### Основные поля
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

### Комментарий
Состояние card полностью задаётся `column_id`: набор состояний и их названия
принадлежат пользователю. В v1 card сознательно **не обязана** иметь assignees,
watchers, attachments, custom fields и dependencies.

## 7. BoardLabel

Метка в рамках доски.

### Основные поля
- id
- board_id
- name
- color
- description
- created_at
- updated_at
- deleted_at

## 8. CardLabel

Связь карточки и метки.
- id
- card_id
- label_id
- created_at

## 9. Checklist

Список подзадач внутри карточки.
- id
- card_id
- title
- position
- created_at
- updated_at
- deleted_at

## 10. ChecklistItem

Элемент чек-листа.
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

## 11. Comment

Комментарий к карточке.
- id
- card_id
- author_user_id
- body
- created_at
- updated_at
- deleted_at

## 12. ActivityEntry

Пользовательская запись истории изменений для board/card UX.

### Основные поля
- id
- workspace_id
- board_id
- card_id nullable
- actor_user_id nullable
- kind
- entity_type
- entity_id
- field_mask
- payload_jsonb
- request_id nullable
- source_change_event_id nullable
- source_audit_log_id nullable
- created_at

### Комментарий
`ActivityEntry` — это read model для user-facing history. Она не заменяет
`ChangeEvent` и не тождественна `AuditLog`.

## 13. AuditLog

Техническая server-side запись аудита.

### Основные поля
- id
- workspace_id nullable
- actor_user_id nullable
- actor_device_id nullable
- actor_replica_id nullable
- action_type
- target_entity_type nullable
- target_entity_id nullable
- request_id nullable
- metadata_jsonb
- created_at

### Комментарий
`AuditLog` нужен для admin/security/diagnostic use-cases и не обязан быть удобным
как основной пользовательский feed.

## 14. Attachment

Future-ready вложение карточки.
В MVP не является обязательной сущностью.
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

## 13. CustomField

Future-ready пользовательское поле доски.
В MVP не является обязательной сущностью.
- id
- board_id
- name
- field_type
- config_json
- position
- created_at
- updated_at
- deleted_at

## 14. CardCustomFieldValue

Future-ready значение кастомного поля для карточки.
В MVP не является обязательной сущностью.
- id
- card_id
- custom_field_id
- value_json
- updated_at
- deleted_at

## 15. Theme

Future-ready переиспользуемая тема оформления.
В MVP продвинутые themes не обязательны.
- id
- workspace_id nullable
- scope
- name
- palette_json
- typography_json
- surface_json
- created_at
- updated_at
- deleted_at

## 16. Wallpaper

Future-ready визуальный фон.
В MVP не является обязательной пользовательской фичей.
- id
- workspace_id nullable
- name
- source_kind
- source_ref
- blur_config_json
- overlay_config_json
- created_at
- updated_at
- deleted_at

## 17. BoardAppearanceSettings

Реализованные настройки внешнего вида доски. В beta поддерживается безопасный
ограниченный набор preset/solid/gradient параметров без загрузки произвольных
assets.
- id
- board_id
- theme_id nullable
- wallpaper_id nullable
- column_style_json
- card_style_json
- density
- created_at
- updated_at

## 18. User

Пользовательская учетная запись.
- id
- email
- username nullable
- display_name
- created_at
- updated_at
- deleted_at

## 19. Device

Устройство пользователя.
- id
- user_id
- display_name
- platform
- public_key nullable
- created_at
- last_seen_at
- revoked_at

## 20. Replica

Логический источник изменений.
В MVP чаще всего соответствует web-клиенту / устройству / клиентскому контексту,
а не отдельному peer-to-peer node как обязательному требованию.
- id
- device_id nullable
- workspace_id nullable
- replica_kind
- protocol_version
- created_at
- last_sync_at
- revoked_at

## 21. ChangeEvent

Нормализованное изменение в журнале синхронизации.
Это прежде всего инфраструктурная sync-ready сущность.
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

## 22. SyncCursor

Прогресс синхронизации между репликами.
- id
- source_replica_id
- target_replica_id
- last_event_id nullable
- last_logical_clock nullable
- updated_at

## 23. Tombstone

Факт удаления сущности для синхронизации.
- id
- entity_type
- entity_id
- deleted_by_replica_id
- deleted_at
- purge_after_at nullable

## 24. IntegrationProvider

Future-ready описание типа интеграции.
- id
- code
- name
- capabilities_json
- is_builtin

## 25. IntegrationConnection

Future-ready подключение конкретного провайдера в workspace.
- id
- workspace_id
- provider_id
- title
- config_json
- secret_ref nullable
- status
- created_at
- updated_at
- deleted_at

## 26. IntegrationLink

Future-ready связь внешнего объекта с нашей сущностью.
- id
- connection_id
- external_object_type
- external_object_id
- local_entity_type
- local_entity_id
- sync_mode
- created_at
- updated_at

## 27. ActivityLog

Журнал значимых событий интерфейса и домена.
В MVP может существовать как технический след или внутренняя структура, но не
обязан сразу становиться отдельной пользовательской фичей.
- id
- workspace_id
- actor_user_id nullable
- actor_replica_id nullable
- entity_type
- entity_id
- action
- payload_json
- created_at


## 12. UserAppearancePreferences

Персональные визуальные предпочтения пользователя.

### Основные поля
- user_id
- app_theme
- density
- reduce_motion
- created_at
- updated_at

## 13. BoardAppearanceSettings

Shared-настройки внешнего вида доски.

### Основные поля
- board_id
- theme_preset
- wallpaper_kind
- wallpaper_value nullable
- column_density
- card_preview_mode
- show_card_description
- show_card_dates
- show_checklist_progress
- custom_properties_jsonb
- created_at
- updated_at

### Комментарий
В v1 это не theme-builder и не asset storage. Настройки хранят preset ids,
базовые display flags и ограниченный JSON object для future-ready расширения.
