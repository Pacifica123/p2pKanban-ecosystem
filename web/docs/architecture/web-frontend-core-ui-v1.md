# Web frontend core UI v1

## Статус

Draft v1 / implementation-ready

## Контекст

На текущем этапе backend уже подтверждает рабочий core happy-path вокруг:

- `workspace / board / column / card`;
- `board activity` и `card activity`;
- auth/session baseline через bearer access token и refresh cookie;
- базового archive/update/delete для уже стабильных сущностей.

Задача этого этапа — не строить local-first, sync или mobile concerns, а собрать **рабочий базовый web-client** вокруг того, что уже реально живет на backend.

## Цель

Собрать первый web-клиент, который покрывает:

- shared UI primitives;
- screen shells;
- workspace list / switcher;
- boards list;
- board screen;
- column/card presentation;
- card details screen;
- loading / empty / error states;
- wiring к существующему backend CRUD;
- минимальные UX-паттерны `create / edit / delete / archive`, где backend уже стабилен.

## Границы этапа

### Входит

- Vite + React + TypeScript web app;
- `react-router-dom` для route-based screen composition;
- `@tanstack/react-query` для server-state;
- `AuthSessionProvider` для sign-in/sign-up/refresh и compatibility `DevSessionProvider` shim для старых компонентов;
- feature-based структура `app / features / shared`;
- board activity panel;
- card history inside card details drawer.

### Не входит

- production-grade account management и security hardening auth UX;
- appearance/customization как отдельный законченный UI-слой;
- local-first persistence beyond temporary client state;
- offline-first;
- sync / distributed / p2p behavior;
- mobile gestures, deep links, background behavior.

---

## 1. Рекомендуемый stack

- React
- TypeScript
- Vite
- React Router DOM
- TanStack Query
- fetch-based thin API client

Это достаточно для первого рабочего клиента и не тащит premature complexity.

---

## 2. Структура каталогов

```text
frontend/
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  .env.example
  src/
    main.tsx
    app/
      App.tsx
      layouts/
        MainLayout.tsx
      providers/
        AppProviders.tsx
        QueryProvider.tsx
        AuthSessionProvider.tsx
        DevSessionProvider.tsx
      router/
        index.tsx
        paths.ts
      styles/
        reset.css
        globals.css
    features/
      workspaces/
        api/
        hooks/
        pages/
      boards/
        api/
        hooks/
        pages/
      columns/
        api/
        hooks/
      cards/
        api/
        hooks/
        components/
      activity/
        api/
        hooks/
        components/
    shared/
      api/
      config/
      lib/
      types/
      ui/
```

Главный принцип: **domain behavior живет в `features`, а не размазывается по `shared`.**

---

## 3. Core screen composition

## `MainLayout`

Отвечает за:

- app shell;
- левый sidebar;
- workspace switcher;
- boards list для активного workspace;
- dev user id control;
- topbar с environment hint.

## `/`

### `WorkspacesPage`

Покрывает:

- list visible workspaces;
- create workspace;
- rename workspace;
- archive workspace;
- переход в boards выбранного workspace.

## `/workspaces/:workspaceId/boards`

### `WorkspaceBoardsPage`

Покрывает:

- list boards in workspace;
- create board;
- rename board;
- archive board;
- переход на конкретный board screen.

## `/workspaces/:workspaceId/boards/:boardId`

### `BoardPage`

Покрывает:

- board summary;
- create column;
- rename/delete column;
- columns strip;
- create card внутри колонки;
- card tile presentation;
- board activity panel;
- открытие card details drawer.

## `?card={cardId}`

### `CardDetailsDrawer`

Покрывает:

- get card detail;
- edit card fields;
- move card between columns;
- archive / unarchive card;
- delete card;
- card history timeline.

---

## 4. Shared UI primitives

Минимальный набор shared primitives для этого этапа:

- `Button`
- `Badge`
- `Panel`
- `TextField`
- `TextAreaField`
- `SelectField`
- `LoadingState`
- `EmptyState`
- `ErrorState`

Пока этого достаточно. Не надо раньше времени делать design-system platform.

---

## 5. API wiring plan

## Workspaces

- `GET /workspaces`
- `POST /workspaces`
- `PATCH /workspaces/{workspaceId}`
- `POST /workspaces/{workspaceId}/archive`

### UI mapping

- `WorkspacesPage` list
- create form
- rename action
- archive action

## Boards

- `GET /workspaces/{workspaceId}/boards`
- `POST /workspaces/{workspaceId}/boards`
- `GET /boards/{boardId}`
- `PATCH /boards/{boardId}`
- `POST /boards/{boardId}/archive`

### UI mapping

- boards list page
- board summary
- rename board
- archive board

## Columns

- `GET /boards/{boardId}/columns`
- `POST /boards/{boardId}/columns`
- `PATCH /boards/{boardId}/columns/{columnId}`
- `DELETE /boards/{boardId}/columns/{columnId}`

### UI mapping

- columns strip
- create column form
- rename column
- delete column

## Cards

- `GET /boards/{boardId}/cards`
- `POST /boards/{boardId}/cards`
- `GET /cards/{cardId}`
- `PATCH /cards/{cardId}`
- `POST /cards/{cardId}/move`
- `POST /cards/{cardId}/archive`
- `POST /cards/{cardId}/unarchive`
- `DELETE /cards/{cardId}`

### UI mapping

- card tiles in columns
- inline create card
- card details drawer
- edit card
- move between columns
- archive/unarchive
- delete

## Activity

- `GET /boards/{boardId}/activity`
- `GET /cards/{cardId}/activity`

### UI mapping

- right-side board activity panel
- card history section inside drawer

---

## 6. Client state model

### Server state

Живет в TanStack Query:

- workspaces
- boards
- board detail
- columns
- cards
- board activity
- card activity

### Temporary client state

Обычный React state:

- create/edit forms;
- drawer open state via route search param;
- temporary dev user id;
- inline form values.

### Что специально не делаем сейчас

- persisted client cache для сущностей;
- offline queue;
- optimistic conflict logic;
- replica-aware client sync model.

---

## 7. Loading / empty / error states

Для каждой страницы и панели должны быть явные состояния:

- loading;
- empty;
- recoverable error;
- action pending.

Это особенно важно на первом web-клиенте, потому что он одновременно служит и UI, и живой integration-surface для backend.

---

## 8. UX паттерны этого этапа

### Разрешено

- inline create;
- `prompt/confirm`-уровень edit/archive для простых сущностей;
- detail drawer для card;
- explicit refresh button;
- simple mutation feedback через disabled buttons.

### Не нужно пока делать

- drag & drop как обязательный baseline;
- heavy optimistic UI;
- deep modal stacks;
- multi-entity bulk actions;
- сложный filter/sort toolbar.

---

## 9. Риски и технические замечания

### 1. Auth transition result

Изначальный web-core этап проектировался вокруг pre-auth bridge, но текущий baseline уже перешел на `auth/session`: API-клиент отправляет `Authorization: Bearer ...`, а `X-User-Id` не является browser default flow.

`DevSessionProvider` остается compatibility shim: он отдает `userId` из текущей authenticated session для старых UI-участков и не должен снова вводить `X-User-Id` как основной путь.

### 2. OpenAPI drift

Для card archive/restore в текущей реальной реализации нужно ориентироваться на подтвержденный backend/smoke happy-path. Если OpenAPI местами расходится с живыми route’ами, фронт на этом этапе должен следовать реально работающему surface, а сам drift лучше отдельно закрыть следующим cleanup-патчем.

### 3. No local-first yet

Нельзя в этом этапе зашивать предположения о будущем offline/sync поведении в UI contracts.

Этот запрет относился именно к этапу web core UI. Полноценные правила local-first data layer, hydration, pending ops и offline UX фиксируются позже отдельным документом `docs/architecture/local-first-data-layer-v1.md`.

---

## 10. Что считаем результатом этапа

Этап считается закрытым, если:

- есть `web-frontend-core-ui-v1.md`;
- есть рабочий Vite React web-client;
- работают workspace list / switcher;
- работают boards list и board screen;
- работают column/card presentation;
- работает card details drawer;
- есть loading / empty / error states;
- есть wiring к текущему backend CRUD;
- есть board activity и card history surface.
