# Beta scope v1

- Статус: Draft v1
- Дата: 2026-04-28
- Назначение: сузить первую beta-границу после прохождения архитектурных, backend, frontend, local-first, sync, security, testing и deployment тем.

> Исторический baseline первоначальной web-first beta. Фактическое состояние
> beta.8, включение Android и актуальные релизные блокеры определяются
> `v1-execution-roadmap.md` и `v1-remaining-checklist.md`. Формулировки ниже о
> полном исключении mobile больше не описывают текущий продукт.

> Этот документ дополняет `docs/product/mvp-scope-v1.md`. MVP scope описывает желаемую первую рабочую версию в широком смысле, а beta scope отвечает на более жесткий вопрос: **что именно должно быть доведено, проверено и упаковано, чтобы это можно было честно назвать v1 beta**.

## Freshness note

Этот документ задает beta-scope и release expectations. Текущий implementation-status теперь нужно читать через `docs/product/v1-execution-roadmap.md`: старые формулировки про labels/checklists/comments, local-first, sync, export и auth/security как еще не реализованные блокеры были superseded последующими baseline-патчами.

Активная граница после truth-sync:

- labels/checklists/comments, local-first runtime, backend-coordinated sync baseline, export backup preview и auth/security baseline считаются baseline-implemented;
- release-gates/real-backend browser evidence, invite-grade account UX и import-as-copy execution остаются отдельными decision points;
- p2p/relay, native mobile, destructive restore, rich conflict UI and production SaaS posture остаются вне v1 unless a later scope patch changes that explicitly.

---

## 1. Зачем нужен beta scope

К этому моменту у проекта уже есть много future-ready контуров: optional p2p, relay/bootstrap, integrations, import/export, local-first, sync, security, deployment, testing и mobile как будущий клиентский слой.

Опасность финального этапа в том, что можно смешать три разных состояния:

1. **Уже реализовано и работает.**
2. **Спроектировано и правильно зарезервировано.**
3. **Хочется иметь в будущем, потому что именно ради этого проект начинался.**

Beta scope нужен, чтобы не обмануться пунктами 2 и 3.

Beta должна быть не архитектурной мечтой, а ограниченной сборкой, которой можно реально пользоваться, показывать, тестировать и дальше развивать без стыда за фундамент.

---

## 2. Главный вывод

Первая beta фиксируется как:

**web-first / local-first self-hostable Kanban planner без native mobile, без обязательного p2p и без внешних интеграций как пользовательского продукта.**

Практическая формула beta:

```text
React web client
+ Axum backend
+ PostgreSQL
+ real auth/session
+ core kanban entities
+ minimal useful card enrichment
+ persistent local store
+ backend-coordinated sync baseline
+ minimal backup/export safety net
+ documented local/self-host deployment
```

Beta **не должна** пытаться одновременно стать:

- full decentralized p2p системой;
- Trello/Jira/Notion replacement со всеми advanced features;
- native mobile продуктом;
- desktop suite с `.exe`, `.AppImage` и mobile APK;
- публичным SaaS без отдельного production-hardening этапа.

---

## 3. Продуктовая интуиция, которую нельзя потерять

Проект начался не ради еще одного CRUD-канбана. Его смысл ближе к такому ощущению:

- свои задачи и проекты должны жить в понятной, спокойной и контролируемой системе;
- приложение должно быть приятным и личным, а не стерильной enterprise-таблицей;
- пользователь не должен чувствовать, что его данные полностью заложены в чужой облачный сервис;
- local-first и будущий optional p2p важны как направление, даже если первая beta еще не реализует full p2p;
- self-host и переносимость данных важны как психологическая и практическая свобода;
- mobile хочется, но не ценой развала core-продукта и вечной незавершенности.

Поэтому beta должна доказать главное: **ядро планировщика уже достаточно живое, устойчивое и полезное, чтобы на него захотелось перенести реальные задачи**.

---

## 4. Текущее состояние архива: честная оценка

### 4.1. Что уже выглядит как beta foundation

В текущем архиве уже есть сильный foundation:

- backend на Axum + PostgreSQL;
- startup migrations;
- account-based auth/session flow;
- access token через `Authorization: Bearer ...` и refresh-cookie;
- legacy `X-User-Id` выключен по умолчанию и оставлен как dev/test fallback;
- core CRUD для `workspaces / boards / columns / cards`;
- web frontend на React/Vite;
- app shell, workspace/board navigation, board screen, card drawer;
- drag-and-drop карточек между колонками;
- user appearance и board appearance;
- board activity, card activity, workspace audit log;
- import/export/integrations contracts как future/stub boundary;
- backend smoke и Rust integration tests;
- frontend Vitest/Testing Library harness и Playwright smoke;
- deployment/env/testing/security docs.

Это уже больше, чем просто skeleton.

### 4.2. Что нельзя считать beta-ready

Следующие зоны нельзя выпускать как будто они полностью готовы, даже после закрытых baseline-патчей:

- release confidence без актуального `release-gates`/UIX bundle, который доказывает real backend product path;
- invite-grade remote beta без account-management UX, password recovery/invite policy, rate limits and deployment-profile evidence;
- import execution/restore без отдельного import-as-copy или restore-safety patch;
- integrations/webhooks как готовые пользовательские интеграции;
- full p2p/relay/bootstrap runtime;
- full conflict-resolution/merge UI;
- native mobile;
- production SaaS security posture.

Labels/checklists/comments, local-first runtime, sync baseline, export backup preview and auth/security baseline are no longer current blockers by themselves; they remain areas that release-gates must prove or honestly classify before beta naming.

---

## 5. Beta release profile

Фиксируются два допустимых beta-профиля.

### 5.1. `beta-local-self-host`

Это основной реалистичный beta-профиль.

Назначение:

- локальное использование;
- private self-host;
- демонстрация проекта;
- использование одним пользователем или очень небольшой доверенной группой;
- проверка жизнеспособности продукта без публичного SaaS-давления.

Допущения:

- один оператор инстанса;
- PostgreSQL под контролем оператора;
- HTTPS желателен для удаленного доступа и обязателен для любого не-local cookie/session сценария;
- публичная регистрация может быть выключена;
- email verification/password reset могут быть отложены только если публичный sign-up выключен и это явно указано в release notes.

### 5.2. `beta-invite-preview`

Это более строгий профиль для маленькой internet-facing beta.

Назначение:

- закрытая beta для ограниченного круга пользователей;
- реальный remote deployment;
- проверка auth/session/security/ops не только на dev-машине.

Требования выше:

- HTTPS;
- secure cookies;
- строгий CORS allowlist;
- explicit CSRF/Origin posture;
- публичный sign-up либо выключен, либо закрыт invite/email verification flow;
- password reset / account recovery path определен;
- rate limits и abuse controls включены;
- дефолтные secrets недопустимы.

`beta-invite-preview` нельзя выпускать по правилам `local_dev`.

---

## 6. Must-have scope

Must-have — это то, без чего beta не считается честной beta-сборкой.

### 6.1. Auth/session и access boundary

Обязательно:

- sign-up / sign-in / refresh / sign-out / sign-out-all;
- session restore в frontend;
- access token только как short-lived bearer state на клиенте;
- refresh cookie с deployment-aware атрибутами;
- `AUTH__ENABLE_DEV_HEADER_AUTH=false` в beta env;
- отсутствие обычного web-flow через `X-User-Id`;
- server-side authz на всех core и derived endpoints;
- Origin/CORS policy, соответствующая выбранному deployment profile;
- rate limits для auth/sensitive endpoints;
- запрет дефолтного `AUTH__JWT_SECRET` вне local dev.

Для `beta-invite-preview` дополнительно обязательно:

- email verification или закрытый invite-only signup;
- password reset/account recovery path;
- подтвержденная refresh rotation/reuse behavior;
- проверенный forced logout-all.

### 6.2. Core Kanban flow

Обязательно:

- создать workspace;
- открыть список workspaces;
- создать board;
- открыть board;
- создать/переименовать/удалить или архивировать column;
- создать/открыть/редактировать/архивировать/удалить card;
- переместить card между columns;
- изменить порядок cards;
- изменить базовые поля card: title, description, priority и start/due date; состояние карточки задаётся её колонкой;
- корректные loading / empty / error / retry states;
- отсутствие white screen при drag-and-drop и card drawer interactions.

Важно: frontend API, backend routes и OpenAPI должны совпадать по этим операциям. Если операция есть в UI, она обязана иметь рабочий backend route и тест.

### 6.3. Минимально полезная карточка

Для beta карточка должна быть не просто “заголовок в колонке”.

Обязательно довести или явно скрыть до post-beta:

- labels;
- checklists;
- comments.

Решение для beta:

- **предпочтительно реализовать минимальный labels/checklists/comments slice**, потому что без него карточка заметно беднее исходного product scope;
- если времени не хватает, нельзя оставлять reachable `not_implemented` routes под видом готовой фичи: UI должен быть скрыт, OpenAPI/README должны честно указать deferred status, а smoke не должен проходить мимо случайно.

Минимальный acceptable slice:

- labels: создать label на board, назначить label card, снять label;
- checklists: создать checklist, добавить item, отметить done/undone, удалить item;
- comments: добавить comment, отобразить comments timeline, удалить/редактировать свой comment.

### 6.4. Appearance/customization

Обязательно:

- user appearance settings;
- board appearance settings;
- theme mode `system | light | dark`;
- preset/solid/gradient wallpapers без file uploads;
- сохранение и повторное чтение настроек;
- frontend применение appearance без визуального развала layout.

Не обязательно:

- uploaded wallpapers;
- arbitrary theme/token editor;
- external theme import.

### 6.5. Activity/history/audit

Обязательно:

- board activity feed;
- card history timeline;
- workspace audit log для admin/debug use-case;
- события на основные mutation flows;
- понятная сортировка по времени;
- отсутствие sensitive secrets в activity/audit payload.

Не обязательно:

- глобальный activity center;
- rich diff viewer;
- compliance dashboard;
- notifications поверх activity.

### 6.6. Local-first runtime baseline

Beta обязана доказать local-first не только в документах.

Минимум:

- persistent local store для `workspaces / boards / columns / cards`;
- локальные metadata `synced / pending / failed` хотя бы для core entities;
- локальный read flow: warm start показывает сохраненные данные без обязательного blocking fetch;
- pending queue для create/update/delete/reorder core operations;
- offline read для уже гидрированных данных;
- offline create/edit/reorder для board screen в пределах разумного core slice;
- reconnect flush pending operations;
- user-visible sync/offline badges: `Offline`, `Saved locally`, `Syncing`, `Sync failed`.

Не обязательно в beta:

- идеальная offline работа для всех future сущностей;
- full local DB encryption;
- advanced manual conflict resolution UI для всех edge cases.

### 6.7. Backend-coordinated sync baseline

Beta не обязана иметь p2p, но обязана иметь честный baseline для синхронизации local-first клиента с backend.

Минимум:

- replica registration;
- `replicaSeq` как обязательный порядок исходящих событий одной реплики;
- push accepted/duplicate/rejected result model;
- incremental pull по cursor/server order;
- idempotency по `eventId` и/или `(replicaId, replicaSeq)`;
- tombstone-aware delete для sync-visible core entities;
- frontend-visible sync status;
- deterministic apply без дубликатов карточек/колонок.

Если sync pipeline не готов, beta должна называться не local-first beta, а online-first preview. Для текущего проекта это нежелательно, потому что local-first — одно из центральных обещаний.

### 6.8. Data ownership: минимальный backup/export safety net

Для beta нужен хотя бы один практический путь не потерять и не запереть пользовательские данные.

Обязательно:

- экспорт workspace или board в versioned JSON/bundle;
- manifest с версией формата;
- понятное предупреждение о том, что включено и что не включено;
- import as copy или preview-only restore path;
- отказ от silently destructive import.

Не обязательно:

- GitHub/Obsidian integrations;
- webhooks;
- binary attachments;
- encrypted backup UX;
- scheduled backups.

Причина: beta может не иметь всех интеграций, но должна уважать исходное желание проекта — данные пользователя не должны ощущаться заложниками приложения.

### 6.9. Packaging and local/self-host workflow

Обязательно:

- корневой README с актуальным quickstart;
- backend `.env.example` без dangerous beta defaults;
- frontend `.env.example`;
- Docker Compose для PostgreSQL dev path;
- `cargo run` local backend path;
- `npm run dev` local frontend path;
- `cargo build --release` documented path;
- `npm run build` documented path;
- инструкции для same-origin reverse proxy или хотя бы self-host baseline;
- миграции с чистой БД проходят на старте.

---

## 7. Nice-to-have scope

Nice-to-have можно делать до beta, если оно не ворует время у blockers.

### 7.1. Product polish

- поиск/filter cards на board;
- быстрые keyboard shortcuts;
- более приятные empty states;
- compact/comfortable density polish;
- card cover/accent color без file uploads;
- better activity text.

### 7.2. Collaboration polish

- UI управления workspace members;
- простые роли owner/member/viewer;
- member activity filter;
- better forbidden/permission UX.

### 7.3. Installability

- PWA manifest;
- offline app shell caching;
- install prompt;
- favicon/icons polish.

PWA допустима как приятный bridge к “приложению на устройстве”, но не должна подменять native mobile scope.

### 7.4. Data portability polish

- export download UI;
- import preview UI;
- board-level import-as-copy;
- dry-run import report;
- human-readable backup summary.

### 7.5. Test/ops polish

- real-backend browser smoke в дополнение к mocked smoke;
- release checklist script;
- migration reset script для test DB;
- basic Dockerfile для backend preview.

---

## 8. Explicitly out of beta

Следующее сознательно не входит в beta.

### 8.1. Native mobile

Не входит:

- Android APK;
- iOS app;
- React Native/Expo app;
- mobile-specific sync hardening;
- mobile UX parity.

Mobile остается отдельным этапом после web/local-first/sync stabilization.

### 8.2. Full p2p / relay / bootstrap

Не входит:

- прямой p2p exchange как пользовательский сценарий;
- NAT traversal;
- discovery;
- relay deployment;
- relay-assisted multi-device sync.

В beta остается backend-coordinated sync. P2P сохраняется как архитектурное направление, но не как release promise.

### 8.3. External integrations

Не входит:

- GitHub integration;
- Obsidian integration;
- production webhooks;
- external provider auth;
- service accounts.

Import/export может быть beta must-have как локальный data ownership tool, но это не означает готовую integrations platform.

### 8.4. Advanced project-management suite

Не входит:

- custom fields;
- dependencies;
- timelines/calendar views;
- automations/rules;
- notifications;
- rich text editor as mandatory baseline;
- attachments/files;
- watchers;
- advanced reporting.

### 8.5. Production SaaS hardening

Не входит как beta baseline:

- multi-tenant public SaaS ops;
- billing;
- admin/support console;
- SOC2/ISO-style compliance;
- full anomaly detection;
- MFA/passkeys;
- E2EE.

---

## 9. Mobile decision for v1 beta and after

### 9.1. Решение для beta

**Mobile не входит в v1 beta.**

Это не отказ от mobile. Это защита проекта от преждевременного platform spread.

Причина:

- beta должна сначала доказать, что core planner действительно стоит переносить на устройства;
- local-first/sync слой должен стабилизироваться на web, иначе mobile начнет копировать незрелую модель;
- premature APK/iOS release создаст иллюзию универсальности, но увеличит число мест, где можно потерять данные или UX.

### 9.2. Репозиторий для будущей mobile-версии

Предпочтительное решение после beta:

**один GitHub monorepo, но разные release channels.**

Будущая структура может выглядеть так:

```text
backend/
frontend/
mobile/
packages/
  api-contracts/
  sync-schemas/
  domain-types/
docs/
```

Почему не отдельный repo сразу:

- проект пока ведется одним логическим потоком;
- backend/API/sync contracts должны эволюционировать вместе;
- AI-assisted patch workflow проще в одном архиве/репозитории;
- mobile будет сильно зависеть от уже принятых domain/sync/security решений.

Когда отдельный repo может стать оправданным:

- mobile получает отдельную команду и релизный цикл;
- общие контракты публикуются как versioned package;
- monorepo становится реально тяжелым и мешает сборке/CI;
- mobile начинает жить как продукт с независимой дорожной картой.

До этого отдельный repo скорее добавит путаницы, чем решит проблему.

### 9.3. Release model для платформ

Не нужно думать о будущем как об одном “универсальном бинарнике”. Правильнее думать о разных artifacts из одного project source:

- web/self-host beta: backend binary/container + frontend static bundle;
- future PWA: web artifact + installability metadata;
- future desktop: отдельный wrapper/channel, если он понадобится;
- future Android: APK/AAB из `mobile/`;
- future iOS: TestFlight/App Store build из `mobile/`.

Эти artifacts не обязаны выходить одновременно.

Главное правило:

**web beta не блокируется mobile, а mobile позже не должен переписывать core contracts под себя.**

### 9.4. Когда начинать mobile architecture chat

Mobile-чат имеет смысл открывать после выполнения трех условий:

1. web beta core flow стабилен;
2. local-first persistent store и sync baseline работают хотя бы для core entities;
3. API/sync contracts перестали часто ломаться.

До этого mobile architecture будет слишком сильно гадать по незавершенному фундаменту.

---

## 10. Beta backlog

### 10.1. P0 — release blockers after baseline patches

| Area | Что сделать | Почему blocker |
|---|---|---|
| Release evidence | Прогнать или честно классифицировать `release-gates`/UIX real backend product path на managed runtime/test DB | Без свежего bundle нельзя отличить готовый user path от старой надежды в документах |
| Contract parity guard | Подтвердить, что OpenAPI, backend routes и frontend API calls не разошлись после закрытых baseline slices | Beta не должна содержать UI-кнопки, ведущие в 404/501/not_implemented |
| Auth/account beta profile | Решить, достаточно ли `beta-local-self-host`, или нужен `beta-invite-preview`; для invite-preview закрыть account recovery/invite/rate-limit evidence | Нельзя случайно назвать local-dev posture internet-facing beta |
| Import boundary | Закрыто: board-level import-as-copy выполняется после preview; merge/destructive restore остаются вне beta | Пользовательские данные нельзя подвергать destructive/ambiguous restore behavior |
| Release notes / limitations | Обновить known limitations по фактическому gate bundle | Release должен честно сказать, что проверено, что skipped и что deferred |

Baseline-implemented areas such as labels/checklists/comments, local-first runtime, sync baseline, export backup preview and auth/security guards are no longer backlog items by themselves; they become release-evidence requirements.

### 10.2. P1 — beta completeness

| Area | Что сделать | Почему важно |
|---|---|---|
| Appearance polish | Проверить темы/обои/плотность на основных экранах | Это часть “личного” ощущения приложения |
| Activity copy | Сделать activity текст понятным пользователю | История должна помогать, а не быть raw log |
| Member UI | Минимальный UI members/roles, если beta обещает small-team use | Иначе beta лучше позиционировать как personal-first |
| Import-as-copy UX | Реализовано для board-level bundle; проверить real-backend smoke и cleanup ошибки | Снижает риск порчи данных |
| Real-backend browser confidence | Расширять сценарии после P0 release evidence checkpoint | Ловит CORS/session/runtime расхождения |
| Error UX | Причесать 401/403/409/offline/sync failed states | Пользователь должен понимать, что происходит |

### 10.3. P2 — post-beta

| Area | Что отложить |
|---|---|
| Mobile | React Native/Expo или другой подход, отдельный architecture chat |
| P2P/relay | Transport rollout после backend-coordinated sync |
| Integrations | GitHub, Obsidian, webhooks, provider auth |
| Advanced cards | Attachments, relations, custom fields, watchers |
| Desktop packaging | `.exe`, `.AppImage`, installers/wrappers |
| Advanced security | MFA, passkeys, E2EE, local DB encryption |
| Automation | Rules, notifications, recurring tasks |

---

## 11. Release gates

### 11.1. Functional gates

Beta нельзя выпускать, если:

- sign-up/sign-in/session restore не работают end-to-end;
- core board flow не проходит вручную и smoke-тестом;
- card drag-and-drop может привести к white screen;
- frontend показывает действия, которых нет в backend;
- reachable backend route возвращает `not_implemented` для заявленной beta-фичи;
- labels/checklists/comments регрессируют в состояние “видно, но не работает”;
- local-first/offline status не работает для core flow;
- sync baseline не может безопасно flush/pull core changes or release evidence cannot prove/classify it;
- export/backup promise заявлен, но пользователь не может получить реальный переносимый bundle.

### 11.2. Security gates

Для любого beta кроме strictly local private dev нельзя выпускать, если:

- включен production-доступ через `X-User-Id`;
- используется default JWT secret;
- CORS wildcard или незафиксированный allowlist;
- cookie policy не соответствует deployment model;
- refresh/session revocation behavior не проверен;
- rate limit middleware выключен или не покрывает auth/sensitive routes;
- derived endpoints `activity/audit/export/sync` обходят access boundary;
- logout/sign-out-all не очищает session-bound frontend state;
- логи могут раскрывать tokens/passwords/secrets.

### 11.3. Quality gates

Перед beta должны пройти:

```bash
cd backend
cargo test
python tests/smoke_core_api.py
```

```bash
cd frontend
npm run build
npm run test:run
npm run test:browser
```

Дополнительно желательно:

- миграции на пустой БД;
- smoke на повторном прогоне без ручной очистки dirty dev state;
- contract check по OpenAPI для touched endpoints;
- один manual clean-machine quickstart.

### 11.4. Operational gates

Перед beta должны быть готовы:

- актуальные `.env.example`;
- documented local dev startup;
- documented self-host startup;
- release notes с known limitations;
- backup/export warning;
- no hidden requirement вроде “надо помнить локальный патч с другой машины”;
- version/tag naming policy.

Текущий beta tag:

```text
v1.0.0-beta.3
```

Линия beta.2 использовалась для предыдущей release-evidence подготовки.
После добавления transport foundation и zero-config bootstrap текущим
кандидатом является beta.3. Если новый полный прогон или artifact smoke не
пройдут, публикацию нужно задержать, а не повышать версию до stable.

Обязательные beta.3 artifacts:

- `p2pkanban-v1.0.0-beta.3-bootstrap.zip`;
- финальный `release-gates_*.zip`;
- `SHA256SUMS.txt`.

Отдельные Windows `.exe` и Linux AppImage больше не являются обязательными:
основной runtime собирается и запускается через Docker.

---

## 12. Demoable flows

Beta должна демонстрироваться не через список endpoint'ов, а через живые сценарии.

### Flow 1 — first run and personal board

1. Пользователь открывает web app.
2. Регистрируется или входит.
3. Создает workspace.
4. Создает board.
5. Создает columns: `Backlog`, `Doing`, `Done`.
6. Создает несколько cards.
7. Перетаскивает card между columns.
8. Открывает card drawer и редактирует детали.

### Flow 2 — useful card

1. Пользователь открывает card.
2. Добавляет description.
3. Добавляет label.
4. Добавляет checklist items.
5. Отмечает item как done.
6. Оставляет comment.
7. Видит эти действия в card history.

### Flow 3 — customization

1. Пользователь меняет app theme.
2. Пользователь меняет board appearance.
3. Перезагружает приложение.
4. Видит, что внешний вид сохранился.

### Flow 4 — local-first resilience

1. Пользователь открывает уже гидрированную board.
2. Отключает сеть.
3. Создает или редактирует card.
4. Видит `Saved locally` / `Changes pending`.
5. Включает сеть.
6. Видит `Syncing` -> `Synced` без ручного восстановления.

### Flow 5 — small team or personal-only honesty

Вариант A, если members UI готов:

1. Owner добавляет member в workspace.
2. Member видит board.
3. Member меняет card в рамках роли.
4. Owner видит activity.

Вариант B, если members UI не готов:

1. Beta позиционируется как personal-first.
2. Backend membership остается API-level capability.
3. Release notes честно говорят, что team UX будет позже.

Нельзя показывать small-team beta, если пользовательский members flow отсутствует.

### Flow 6 — data ownership

1. Пользователь экспортирует workspace или board.
2. Получает versioned bundle.
3. Видит manifest/summary.
4. Может импортировать как copy или хотя бы пройти preview.

### Flow 7 — self-host confidence

1. Новый checkout проекта.
2. Поднят PostgreSQL.
3. Запущен backend.
4. Запущен frontend или собран static bundle.
5. Пройден smoke.
6. Нет ручных “магических” шагов, которые не описаны в README.

---

## 13. Beta acceptance matrix

| Capability | Beta decision | Notes |
|---|---|---|
| Web app | Must-have | Primary client |
| Backend API | Must-have | Modular monolith |
| PostgreSQL | Must-have | Separate persistent service |
| Auth/session | Must-have | Real flow, not `X-User-Id` |
| Workspaces/boards/columns/cards | Must-have | Core product |
| Drag-and-drop cards | Must-have | Basic Kanban expectation |
| Labels/checklists/comments | Must-have or hidden | Prefer must-have implementation |
| Appearance | Must-have | Already part of product identity |
| Activity/history | Must-have minimal | Board/card/workspace surfaces |
| Local-first persistent store | Must-have | Core promise |
| Backend-coordinated sync | Must-have baseline | No p2p required |
| Import/export backup | Must-have minimal export | Data ownership safety net |
| Integrations | Out | Keep stubs/internal contracts only |
| P2P/relay | Out | Future transport phase |
| Native mobile | Out | Future architecture phase |
| Desktop packaging | Out | Optional after web beta |
| Public SaaS | Out | Needs separate hardening |
| PWA installability | Nice-to-have | Useful bridge, not blocker |

---

## 14. How to treat contradictions with older docs

Если старый документ говорит “входит в MVP”, а beta scope говорит “out of beta”, то для релиза применяется beta scope.

Если старый документ говорит “future/stub”, а beta scope говорит “must-have”, это означает не противоречие, а изменение release bar: фичу нужно либо реализовать, либо честно перенести и убрать из beta promise.

Практическое правило:

**beta-scope-v1.md является release-plan overlay поверх docs v1/v2, а не заменой всей архитектуры.**

---

## 15. Итог

Первая beta должна быть узкой, но настоящей:

- web-first;
- self-hostable;
- local-first в runtime, а не только в ADR;
- с реальным auth/session;
- с рабочим core Kanban;
- с полезной карточкой;
- с appearance и activity;
- с минимальным export/backup safety net;
- без native mobile и без p2p как beta promise.

Mobile остается важной частью долгосрочного чувства проекта, но правильный путь — **сначала сделать достойное web/local-first ядро, затем добавить mobile в тот же monorepo как отдельный release channel**, не ломая уже стабилизированные контракты.
