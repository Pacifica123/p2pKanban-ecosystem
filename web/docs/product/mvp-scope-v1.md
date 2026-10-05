# Product scope v1 / MVP

- Статус: Draft v2
- Дата: 2026-04-01

> Это исходная граница MVP. Текущая реализация beta.8 уже шире, включая
> Android и roaming. Для фактической готовности используйте
> `v1-execution-roadmap.md`; этот документ сохраняется как история продуктовых
> решений.

## Зачем нужен этот документ

Этот документ фиксирует **продуктовый срез первой рабочей версии**.
Он отвечает на вопрос не "что архитектура в принципе допускает", а "что мы
реально обязуемся довести до usable v1".

Важно:
- наличие сущности в `domain/`, `architecture/` или `api/` не означает, что она
  автоматически входит в первую рабочую версию;
- v1 — это **ограниченный, но реально доводимый** набор возможностей;
- future-proof элементы в модели данных допустимы, если они не раздувают first scope;
- local-first в v1 означает **локально устойчивый web UX**, а не обещание fully
  backendless продукта или full p2p.

## Продуктовая цель v1

Собрать **полезный web-first local-first Kanban planner**, который:
- подходит для личного использования и небольших команд;
- позволяет стабильно работать с досками, колонками и карточками;
- не разваливает пользовательский сценарий при кратковременной потере сети;
- использует backend как основной HTTP/API, auth/session слой и sync-координатор;
- не требует реализации full p2p, mobile и интеграций уже на первом этапе.

Иными словами, v1 должен доказать жизнеспособность цепочки:
`workspace -> board -> column -> card -> local changes in web client -> sync through backend`.

## Что означает local-first в пределах v1

В этом проекте local-first **не** трактуется как:
- обязательная работа без backend вообще;
- полный peer-to-peer сценарий;
- полноценный offline-first install/runtime для любых браузеров и устройств;
- отсутствие серверной координаты истины в web MVP.

Для v1 local-first означает:
- клиент хранит локальное состояние и pending changes в объеме, достаточном для
  устойчивого UX;
- пользователь может вносить изменения при кратковременной нестабильности сети;
- после восстановления соединения изменения синхронизируются через backend;
- архитектура не запрещает дальнейший переход к richer sync и optional p2p.

## Что входит в MVP scope

### 1. Web-клиент как первый и основной клиент
В v1 входит:
- основной web UI;
- базовая навигация между workspace и boards;
- рабочий board screen;
- формы и действия, достаточные для everyday use.

В v1 не требуется:
- нативный mobile-клиент;
- отдельный desktop-клиент;
- parity между несколькими типами клиентов.

### 2. Базовая identity/auth-модель для web
В v1 входит:
- базовая аутентификация пользователя;
- пользовательская сессия для web;
- привязка действий к `user` и `device`;
- минимальная модель `replica` как инфраструктурного источника изменений.

Детальная и расширенная security-модель может развиваться позже, но v1 должен
иметь достаточную основу для приватных workspace и авторизованных изменений.

### 3. Workspace и минимальная коллаборация
В v1 входит:
- создание workspace;
- просмотр списка доступных workspace;
- базовое membership-управление;
- минимальные роли уровня workspace;
- приватная модель доступа без public sharing.

В v1 не входит как обязательная фича:
- приглашение по публичной ссылке;
- guest access;
- board-level ACL;
- сложные invitation flows.

### 4. Boards и columns
В v1 входит:
- создание, редактирование, архивирование board;
- создание, редактирование, удаление columns;
- reorder columns;
- произвольное число columns в рамках board.

Board — основная рабочая поверхность v1.

### 5. Core cards
В v1 входит:
- создание, чтение, редактирование и удаление card;
- перенос card между columns;
- reorder cards внутри column;
- базовые поля card:
  - title;
  - description;
  - priority;
  - due date / start date;

Состояние карточки не является отдельным enum: её колонка и есть статус в
канбан-смысле. Пользователь сам задаёт любое число колонок и их названия.

В v1 card **не обязана** иметь:
- attachments;
- assignees;
- watchers;
- custom fields;
- relations/dependencies.

### 6. Минимальное обогащение карточек
В v1 входит:
- labels;
- checklists;
- comments.

Это минимальный набор, делающий карточку практически полезной, не превращая v1
в перегруженный task-suite.

### 7. Local-first поведение в web-сценарии
В v1 входит:
- локальное хранение состояния на клиенте в объеме, достаточном для local-first UX;
- optimistic updates там, где это уместно;
- корректная работа при временной потере сети;
- последующая синхронизация через backend после восстановления соединения.

Важно: в v1 это **не означает full offline product** со всеми гарантиями для
любых устройств и транспортов. Это означает, что пользовательский сценарий не
должен разваливаться при кратковременной нестабильности сети.

### 8. Sync-ready backend foundation
В v1 входит:
- backend как единая точка HTTP/API доступа;
- учет `device` / `replica` на уровне модели;
- tombstone-aware deletion и курсоры в объеме, достаточном для дальнейшего sync-слоя;
- идемпотентная обработка изменений там, где это уже требуется моделью.

Важно:
- это **не требует** вывода full sync UX на уровень пользователя уже в первом релизе;
- это **не означает** peer-to-peer transport в MVP;
- это означает, что мы не закладываем тупиковую CRUD-only архитектуру.

## Core use-cases v1

### UC-01. Личный workspace для повседневного планирования
Пользователь создает workspace, заводит одну или несколько boards, настраивает
columns и ведет свои задачи в карточках.

### UC-02. Управление потоком задач на Kanban-доске
Пользователь создает card, перемещает ее между columns, меняет приоритет,
дедлайн, статус и порядок отображения.

### UC-03. Декомпозиция задачи внутри карточки
Пользователь добавляет checklist и отмечает выполнение пунктов, не создавая для
каждой мелочи отдельную card.

### UC-04. Быстрая организация и сохранение контекста
Пользователь использует labels, описание и comments, чтобы не терять смысл
задачи и договоренности по ней.

### UC-05. Базовая совместная работа небольшой команды
Небольшая команда работает в одном workspace: видит общие boards, меняет карточки
в рамках прав и оставляет comments.

### UC-06. Работа при нестабильной сети
Пользователь открывает web-клиент, вносит изменения локально, временно теряет
сеть и после восстановления продолжает работу без ручного восстановления данных.

### UC-07. Архивация и удаление без потери доменного смысла
Workspace/board/card можно не только создавать, но и переводить в неактивное
состояние или удалять так, чтобы это корректно отражалось в модели и sync-ready
инфраструктуре.

### UC-08. Понимание недавних изменений без ручного расследования
Пользователь открывает board или card и видит минимальную, но понятную историю:
кто создал карточку, кто перенес ее между колонками, кто добавил comment или
отметил checklist item.

## Что сознательно не берем в v1

### 1. Full p2p / relay / bootstrap / discovery
Не входит:
- прямой peer-to-peer обмен как обязательный пользовательский сценарий;
- discovery peers;
- NAT traversal;
- relay/bootstrap инфраструктура;
- полноценный multi-device p2p UX.

Причина: это сильно раздувает scope и уже отдельно зафиксировано как не-MVP.

### 2. Native mobile
Не входит:
- Android/iOS клиент;
- отдельная mobile sync-специфика;
- mobile-first UX-проработка.

### 3. Advanced permissions и sharing
Не входит:
- public boards;
- guest access;
- приглашения по ссылке;
- board-level ACL overrides;
- временные роли и сложная RBAC/ABAC-модель.

### 4. Heavy card model beyond core
Не входит:
- attachments/files;
- assignees;
- watchers;
- card relations/dependencies;
- rich editor как обязательная часть v1.

### 5. Advanced board/productivity features
Не входит:
- board views;
- saved filter presets;
- templates;
- automations/rules;
- notifications/reminders;
- календарные режимы и timeline-представления.

### 6. Minimal customization / appearance
Входит ограниченный, но реальный customization slice:
- пользовательская тема приложения (`system | light | dark`);
- board appearance settings;
- preset/solid/gradient wallpapers без файловых ассетов;
- плотность отображения и базовые display toggles для board.

Не входит:
- uploaded image wallpapers;
- arbitrary palette/token editors;
- импорт внешних тем;
- сложные per-column/per-card style presets.

### 7. Custom fields
Не входит:
- пользовательские типы полей;
- сложная валидация значений;
- UX-конструктор схем карточки.

### 8. Integrations / import / export
Не входит:
- GitHub / Obsidian / webhooks;
- import/export jobs как пользовательская фича;
- backup/restore UX;
- service accounts и внешние adapter flows.

### 9. Продвинутый activity/audit surface за пределами минимального history slice
Входит ограниченный, но реальный activity slice:
- board-level recent activity;
- card-level history timeline;
- workspace-level technical audit log для admin use-case.

Не входит:
- отдельный глобальный activity center на весь workspace;
- расширенный audit trail с продвинутой фильтрацией и поиском;
- compliance/security analytics dashboard;
- rich diff viewer для больших текстов;
- notifications/subscriptions, построенные поверх activity.

То есть в v1 берем **history для board/card**, но не берем отдельный большой
product surface вокруг activity/audit.

## Границы v1 в терминах сущностей

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
- User / Device / Replica как инфраструктурная основа

### Допустимы как внутренняя sync-ready инфраструктура v1
- ChangeEvent
- SyncCursor
- Tombstone

### Допустимы в архитектуре, но не обязательны к реализации в v1
- WorkspaceInvitation
- Attachment
- CustomField
- CardCustomFieldValue
- UserAppearancePreferences
- Theme
- Wallpaper
- BoardAppearanceSettings
- IntegrationProvider
- IntegrationConnection
- IntegrationLink
- ActivityEntry
- AuditLog
