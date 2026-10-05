# Appearance / customization v1

- Статус: базовая реализация готова
- Дата актуализации: 2026-07-29

## Зачем нужен этот документ

Документ фиксирует реализованный минимальный backend/frontend slice настройки
внешнего вида. Файловое хранилище обоев и произвольный CSS всё ещё отложены,
но wallpaper по HTTP(S)-ссылке уже входит в рабочий срез.

## Принятый v1-срез

### 1. User-level preferences
Отдельная сущность `UserAppearancePreferences` хранит персональные UX-предпочтения:
- `app_theme`
- `density`
- `reduce_motion`
- `checklist_item_submit_mode`: `ctrl_enter | enter | button`
- `card_details_mode`: `drawer | modal`

Это настройки пользователя, а не workspace или board.

### 2. Board-level shared appearance
Отдельная сущность `BoardAppearanceSettings` хранит общую конфигурацию доски:
- `theme_preset`
- `wallpaper_kind`
- `wallpaper_value`
- `column_density`
- `card_preview_mode`
- display toggles
- `custom_properties_jsonb`, где `accentColor` имеет форму `#RRGGBB`

## Почему отдельный модуль `appearance`

Хотя `BoardAppearanceSettings` привязаны к `Board`, это уже отдельный API surface
и отдельная зона эволюции. Поэтому в backend их удобнее выделить в модуль
`appearance`, а не смешивать с `boards`.

Это дает:
- чище router ownership;
- более предсказуемые DTO;
- меньший риск раздувания `boards/service.rs`;
- понятную точку дальнейшего роста до workspace defaults и theme registry.

## API surface v1

### `GET /me/appearance`
Возвращает эффективные пользовательские настройки с дефолтами.

### `PUT /me/appearance`
Создает или обновляет пользовательские настройки.

### `GET /boards/{boardId}/appearance`
Возвращает effective board appearance. Если кастомная запись отсутствует,
backend возвращает дефолты.

### `PUT /boards/{boardId}/appearance`
Создает или обновляет board appearance settings.

## Политика доступа

- `me/appearance` доступен только текущему аутентифицированному пользователю.
- `boards/{boardId}/appearance`:
  - `GET` требует обычного доступа к workspace;
  - `PUT` требует `owner | admin`.

## Wallpaper и акцент

Backend хранит `none | accent | solid | gradient | preset | image`. Для
`image` сохраняется только HTTP(S)-ссылка, а не файл. Для `accent` значение
wallpaper остаётся `null`: клиент строит фон из текущего акцента. Сам акцент
лежит в переносимом `custom_properties_jsonb`, поэтому он входит в board backup
и не заменяет уже выбранный wallpaper.

## Почему `theme_preset` — строка, а не enum

Backend не должен быть жестко привязан к frontend palette registry. Строковый
preset id позволяет:
- раскатывать новые темы без миграции;
- иметь разные preset packs в разных деплоях;
- не ломать API при росте каталога тем.

## Sync и local-first замечание

Appearance settings — это обычное прикладное состояние. Они не требуют особого
transport-режима, но должны оставаться sync-friendly: отдельные таблицы и явные
ресурсы упрощают последующую интеграцию в change/event слой.

## Что оставить на следующий этап, а не на этот

- workspace defaults и inheritance policy;
- merge policy для конфликтов appearance на нескольких клиентах;
- пользовательские overrides поверх shared board appearance;
- asset-backed wallpapers;
- файловое хранилище wallpaper;
- UI-конструктор тем.
