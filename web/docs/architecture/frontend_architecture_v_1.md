# Frontend architecture v1

## Статус

Draft v1

## Контекст

В этом проекте frontend проектируется не как обычный web React client, а как **React Native client**.

При этом reference-проект по-прежнему полезен как источник общих архитектурных принципов:
- feature-based decomposition;
- разделение на `app / features / shared`;
- верхнеуровневые providers;
- централизованный API client;
- отдельные shared types и shared UI.

Но web-специфичные решения из reference-проекта нельзя переносить буквально:
- browser router;
- `react-router-dom`;
- `localStorage` как универсальную основу для session logic;
- page/layout-мышление, завязанное на браузерные route tree.

## Цель документа

Зафиксировать:
- структуру frontend;
- app shell;
- navigation/router model;
- providers;
- место для `shared/ui`, `shared/api`, `shared/types`;
- feature boundaries;
- screen map.

---

## 1. Главный вывод

Переход с обычного React web на React Native **не меняет доменную декомпозицию frontend**, но **меняет platform layer**.

То есть:
- feature boundaries в основном сохраняются;
- shared contracts и API слой сохраняются;
- app composition сохраняется;
- но browser router заменяется на native navigation;
- web storage заменяется на storage abstraction;
- browser layouts заменяются на screen groups / navigators / shell screens;
- shared UI строится на RN primitives, а не на DOM/CSS.

Итоговое решение:

- сохранить архитектурный каркас `app / features / shared`;
- строить frontend как **feature-based React Native app**;
- не проектировать его как «web frontend, который потом как-нибудь адаптируют».

---

## 2. Что уже готово со стороны backend и важно для frontend

На текущий момент frontend уже может опираться на подтвержденный backend surface:

### Уже реально можно подключать
- core CRUD для `workspaces / boards / columns / cards`;
- `me/appearance`;
- `board appearance`;
- `board activity`;
- `card activity`;
- `workspace audit log`.

### Пока не стоит считать завершенным end-to-end UX
- production-grade account/session UX;
- guest/public/shared flow как полностью готовый пользовательский surface;
- полный `labels / checklists / comments` flow.

Следствие для архитектуры:
- app shell и screen map должны строиться вокруг **workspace / board / card / activity / appearance**;
- незавершенные функции должны идти как изолированные modules или feature flags;
- auth/session уже является основным направлением интеграции, но account-management и security hardening нужно держать изолированными от core board UI.

---

## 3. Рекомендуемый frontend stack

## Обязательная база
- React Native
- TypeScript
- Expo — по умолчанию, если не появится жесткая причина идти в bare workflow
- React Navigation
- TanStack Query
- Axios или thin fetch-wrapper

## State / storage
- Auth/session state — через provider/store
- Server state — через TanStack Query
- Sensitive storage — через secure storage abstraction
- Non-sensitive persisted preferences — через async storage abstraction

## Дополнительно
- `react-hook-form` + `zod` для форм
- gesture/reanimated слой — позже, когда дойдем до более богатого board UX
- feature flags для незавершенных backend-направлений

---

## 4. Принципы разбиения frontend

Frontend делится на три главные зоны:

### `app/`
Композиция приложения:
- bootstrap;
- providers;
- navigation;
- root shell;
- environment/config.

### `features/`
Доменные и пользовательские функции:
- auth;
- workspaces;
- boards;
- cards;
- activity;
- appearance;
- позже labels/checklists/comments.

### `shared/`
Общие переиспользуемые строительные блоки:
- api;
- ui primitives;
- types;
- lib/utilities;
- theme;
- storage adapters.

Ключевой принцип:

**Бизнес-функциональность живет в `features`, а не расползается по `shared`.**

---

## 5. Структура каталогов

```text
frontend/
  app/
    App.tsx
    providers/
      AppProviders.tsx
      QueryProvider.tsx
      AuthProvider.tsx
      WorkspaceProvider.tsx
      AppearanceProvider.tsx
    navigation/
      RootNavigator.tsx
      AuthNavigator.tsx
      MainNavigator.tsx
      WorkspaceDrawerNavigator.tsx
      BoardStackNavigator.tsx
      routeNames.ts
      guards.tsx
    shell/
      AppBootstrap.tsx
      AuthGate.tsx
      AppStateBoundary.tsx
    config/
      env.ts
      featureFlags.ts

  features/
    auth/
      api/
      model/
      hooks/
      screens/
      components/
    workspaces/
      api/
      model/
      hooks/
      screens/
      components/
    boards/
      api/
      model/
      hooks/
      screens/
      components/
    cards/
      api/
      model/
      hooks/
      screens/
      components/
    activity/
      api/
      model/
      hooks/
      components/
      screens/
    appearance/
      api/
      model/
      hooks/
      screens/
      components/
    labels/
      api/
      model/
      hooks/
      components/
    checklists/
      api/
      model/
      hooks/
      components/
    comments/
      api/
      model/
      hooks/
      components/
    sync-status/
      model/
      hooks/
      components/

  shared/
    api/
      client.ts
      errors.ts
      interceptors.ts
      authSession.ts
    storage/
      secureStorage.ts
      asyncStorage.ts
      index.ts
    theme/
      tokens.ts
      themes.ts
      spacing.ts
      typography.ts
    ui/
      primitives/
      composite/
      feedback/
    types/
      auth.ts
      workspace.ts
      board.ts
      card.ts
      activity.ts
      appearance.ts
      common.ts
      ids.ts
    lib/
      date.ts
      validation.ts
      pagination.ts
      guards.ts
    config/
      constants.ts

  platform/
    navigation/
    gestures/
    haptics/
    keyboard/
```

---

## 6. App shell

Для React Native app shell — это не browser layout, а композиция из:
- providers;
- bootstrap logic;
- auth gate;
- root navigator;
- global overlays.

### App shell должен включать
- чтение env/config;
- гидрацию session;
- чтение persisted appearance/preferences;
- восстановление active workspace и последних pointers;
- network/sync indicators;
- toast / alert / modal portals.

### Базовая схема запуска
1. Старт приложения
2. `AppBootstrap`
3. Пока идет гидрация — `Splash / Bootstrap screen`
4. После bootstrap:
   - нет session -> `AuthNavigator`
   - есть session -> `MainNavigator`
   - dev/test bootstrap, если явно включен, сначала создает/refresh'ит реальную session и только потом ведет в `MainNavigator`

---

## 7. Router model -> navigation model

Так как это React Native, вместо browser router используется navigation tree.

## Root navigation
- `RootNavigator`
  - `Boot`
  - `Auth`
  - `Main`

## Auth navigator
- `SignInScreen`
- `SignUpScreen`
- опциональный `DevBootstrapScreen` только для явно включенной dev/test сборки; он не должен возвращать `X-User-Id` как основной auth path

## Main navigator
- `WorkspaceDrawerNavigator`
  - `HomeScreen` / overview
  - `BoardsListScreen`
  - `BoardStackNavigator`
  - `SettingsStack`
  - `AppearanceStack`
  - `ActivityStack`

## Board stack
- `BoardScreen`
- `CardDetailsScreen`
- `CardActivityScreen`
- `BoardActivityScreen`
- `BoardAppearanceScreen`

### Guards
Вместо web-style `RequireAuth` и route wrappers используются:
- auth gate на уровне navigator group;
- screen guards для deployment-specific или future features;
- feature flags для surface, который backend пока не довел end-to-end.

---

## 8. Providers

Рекомендуемый верхнеуровневый порядок:

1. `QueryProvider`
2. `AuthProvider`
3. `WorkspaceProvider`
4. `AppearanceProvider`
5. `NetworkProvider` / `SyncStatusProvider`
6. global feedback/modal provider

### `QueryProvider`
Отвечает за:
- server-state cache;
- retry policy;
- invalidation;
- request deduplication.

### `AuthProvider`
Отвечает за:
- bootstrapping текущей session;
- access token lifecycle;
- refresh flow abstraction;
- current user;
- sign-in / sign-out actions.

### `WorkspaceProvider`
Отвечает за:
- active workspace;
- active board pointer;
- workspace switch;
- согласование выбранного контекста с navigation.

### `AppearanceProvider`
Отвечает за:
- effective app theme;
- гидрацию appearance preferences;
- применение пользовательских и board-level appearance settings к UI.

---

## 9. Shared layers

## 9.1. `shared/api`

Должен быть platform-neutral и тонким.

Состав:
- API client;
- interceptors;
- auth header/session binding;
- error normalization;
- refresh policy;
- request helpers.

Важно:
- не завязывать session logic на web-only `localStorage`;
- не смешивать API transport и UI state.

## 9.2. `shared/types`

Нужно разделять типы по доменам, а не складывать все в один общий файл.

Минимальный набор:
- `auth.ts`
- `workspace.ts`
- `board.ts`
- `card.ts`
- `activity.ts`
- `appearance.ts`
- `common.ts`
- `ids.ts`

Отдельно полезно иметь distinction между:
- API DTO types;
- app/domain types;
- navigation param types.

## 9.3. `shared/ui`

Только реально переиспользуемые RN-компоненты.

Примеры:
- `Screen`
- `PageHeader`
- `PrimaryButton`
- `SecondaryButton`
- `TextField`
- `Card`
- `Badge`
- `LoadingState`
- `EmptyState`
- `ErrorState`
- `BottomSheetFrame`

Нельзя складывать в `shared/ui` feature-specific виджеты карточек, досок или аудита.

## 9.4. `shared/storage`

Обязателен отдельный storage abstraction layer:
- secure storage для чувствительных данных;
- async storage для обычных persisted preferences;
- единый адаптер, через который работает auth/session layer.

---

## 10. Feature boundaries

## `features/auth`
Отвечает за:
- sign-in / sign-up / sign-out;
- bootstrap session;
- auth state;
- auth screens.

Не отвечает за:
- workspace selection;
- board data;
- board appearance.

## `features/workspaces`
Отвечает за:
- список workspaces;
- создание workspace;
- переключение workspace;
- workspace-level context.

## `features/boards`
Отвечает за:
- boards list;
- board screen;
- columns;
- board header;
- board-level queries.

## `features/cards`
Отвечает за:
- card details;
- create/edit card;
- move/reorder flow позже;
- card-level projection.

## `features/activity`
Отвечает за:
- board activity feed;
- card history;
- workspace audit log.

## `features/appearance`
Отвечает за:
- user appearance settings;
- board appearance settings;
- mapping preset/theme/wallpaper -> UI theme.

## `features/labels`, `features/checklists`, `features/comments`
Должны быть отдельными модулями, но пока не должны диктовать app shell и базовую navigation model.

## `features/sync-status`
Cross-cutting feature:
- network status;
- sync indicator;
- позже pending changes / last sync.

Но не владеет core board/card feature.

---

## 11. Screen map v1

## Уже можно строить как реальные экраны

### Bootstrap / auth
- `SplashScreen`
- `SignInScreen`
- `SignUpScreen` (если включено конфигом)
- `DevEntryScreen`

### Workspace
- `WorkspaceListScreen`
- `WorkspaceCreateScreen`
- `WorkspaceSettingsScreen`
- `WorkspaceAuditLogScreen`

### Boards
- `BoardsListScreen`
- `BoardScreen`
- `BoardCreateScreen`
- `BoardSettingsScreen`
- `BoardAppearanceScreen`
- `BoardActivityScreen`

### Cards
- `CardDetailsScreen`
- `CardEditScreen`
- `CardActivityScreen`

### Settings
- `UserAppearanceScreen`
- `AccountScreen`
- `AboutScreen`

## Лучше пока как skeleton / feature flag
- `LabelsScreen`
- `ChecklistEditorScreen`
- `CommentsScreen`
- `DevicesAndSessionsScreen`
- `PublicAccessScreen`
- `SharedAccessScreen`

---

## 12. Data flow policy

## Server state
Через TanStack Query:
- workspaces;
- boards;
- columns;
- cards;
- board activity;
- card activity;
- workspace audit log;
- appearance resources.

## App/session state
Через providers/store:
- auth session;
- current user;
- active workspace;
- active board pointer;
- effective theme;
- global UI state.

## Local UI state
Оставляется внутри screens/components:
- draft forms;
- local search input;
- tab state;
- modal open/close;
- transient selection state.

---

## 13. Практический приоритет реализации

Рекомендуемый порядок первого frontend-этапа:

1. `app/providers`
2. `app/navigation`
3. `shared/api`
4. `shared/types`
5. `shared/ui/primitives`
6. `features/auth`
7. `features/workspaces`
8. `features/boards`
9. `features/cards`
10. `features/activity`
11. `features/appearance`

Следующим слоем:
- `labels`
- `checklists`
- `comments`
- `sync-status`

---

## 14. Итог

Для этого проекта принимается следующая frontend-архитектура v1:

- основа — **feature-based decomposition**;
- верхний каркас — `app / features / shared`;
- frontend реализуется как **React Native application**, а не как web app с механической адаптацией;
- browser router заменяется на navigation tree;
- app shell строится через providers + bootstrap + auth gate + navigators;
- `shared/api`, `shared/types`, `shared/ui`, `shared/storage` выделяются явно;
- core frontend flow первой рабочей версии строится вокруг:
  - workspaces;
  - boards;
  - cards;
  - activity;
  - appearance.

Незавершенные backend-направления не блокируют архитектуру, но выносятся в отдельные feature modules и при необходимости прикрываются feature flags.

