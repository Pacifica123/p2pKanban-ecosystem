# Testing application guide v1

## 1. Назначение

Этот документ — практическая инструкция по тестированию приложения в целом.
Он дополняет:

- `testing-strategy-v1.md`;
- `testing-pyramid-v1.md`;
- `backend/tests/SMOKE_SCENARIOS.md`.

Если strategy отвечает на вопрос **что и зачем проверять**, то этот guide отвечает на вопрос **как именно запускать проверки локально на текущем этапе проекта**.

## 2. Слои проверок на текущем этапе

### Backend
- Rust integration tests в `backend/tests/*.rs`;
- Python smoke `backend/tests/smoke_core_api.py`;
- ручная проверка миграций через запуск backend на чистой БД.

### Frontend
- Vitest unit/integration tests в `frontend/src/test/**/*.test.ts(x)`;
- browser smoke сейчас находится в переходном состоянии: legacy Playwright specs в `frontend/e2e/smoke/**/*.smoke.spec.ts` должны быть заменены кастомным UI/UX Evidence Runner согласно `docs/development/custom-uiux-evidence-manifesto-v1.md`.

## 3. Предварительные условия

### Backend prerequisites
Нужно подготовить PostgreSQL и backend env.

Минимум:
- доступная PostgreSQL база;
- рабочий `DATABASE_URL` или `TEST_DATABASE_URL` для integration tests;
- возможность поднять backend на `127.0.0.1:18080`.

### Frontend prerequisites
Нужно один раз установить frontend dependencies:

```bash
cd frontend
npm install
```

Legacy Playwright browser smoke временно требует браузеры Playwright. Целевая post-Phase-7 архитектура должна убрать это требование и заменить его системным browser discovery для кастомного UI/UX Evidence Runner:

```bash
cd frontend
npx playwright install
```

## 4. Рекомендуемый локальный порядок проверок

Лучший базовый порядок такой:

1. быстрые frontend unit/integration;
2. backend Rust integration tests;
3. поднять backend;
4. backend Python smoke;
5. frontend browser smoke.

Это дает быстрый feedback в начале и живую end-to-end проверку в конце.

## 5. Frontend: unit и integration

### Запуск всего frontend test harness

```bash
cd frontend
npm run test:run
```

### Запуск в watch-режиме

```bash
cd frontend
npm test
```

### Что сейчас реально покрыто

На текущем этапе frontend harness уже должен проверять:
- pure helpers;
- HTTP client behavior на уровне error/data envelope;
- feature-level rendering на примере WorkspacesPage;
- create mutation wiring без поднятого backend.

### Где писать следующие tests

- `src/test/unit/` — helpers, selectors, formatters, pure UI logic;
- `src/test/integration/` — feature/screen tests с mocked fetch/local boundaries;
- `src/test/contracts/` — shape compatibility tests для HTTP/sync payloads;
- `src/test/factories/` — builders для workspace/board/column/card/activity payloads.

## 6. Backend: Rust integration tests

### Запуск всех integration tests

```bash
cd backend
cargo test
```

### Запуск выборочно

```bash
cd backend
cargo test --test core_crud_smoke -- --ignored
cargo test --test appearance_smoke -- --ignored
```

### Что важно помнить

- Rust integration tests ожидают предсказуемую тестовую БД;
- нельзя полагаться на уже "грязное" состояние dev-базы;
- миграции должны быть актуальны и согласованы с `sqlx::migrate!()`.

## 7. Backend: black-box smoke

Сначала нужно поднять backend.

```bash
cd backend
cargo run
```

После этого в отдельной консоли:

```bash
cd backend
python tests/smoke_core_api.py
```

### Что smoke обязан подтвердить

- health;
- sign-up / sign-in / session;
- workspaces / boards / columns / cards;
- appearance surface;
- activity / audit;
- sign-out-all и корректный `401` после logout.

Если smoke падает, сначала проверяются:
- поднят ли backend;
- тот ли `BASE_URL` использует smoke;
- чисты ли assumptions внутри smoke;
- не потерян ли CORS/auth wiring: `Authorization` header, refresh cookie credentials и allowlist origins.

## 8. Frontend: browser smoke / UI/UX evidence

Browser smoke держится маленьким и проверяет только критичный UI path. Post-Phase-7 решение: Playwright является legacy transition layer, а целевым механизмом должен стать кастомный UI/UX Evidence Runner.

### Текущий legacy-запуск

```bash
cd frontend
npm run test:browser
```

### Целевой запуск после миграции

```bash
python tools/uiux_probe.py --base-url http://127.0.0.1:5173/ --scenario mocked-auth-workspace
```

### Что он делает сейчас

- открывает auth screen;
- выполняет mocked sign-in;
- подтверждает загрузку workspace list;
- падает, если в браузере возникает `pageerror`.

### Почему browser smoke сейчас mocked

Для MVP важнее иметь:
- короткую и стабильную browser smoke проверку;
- быстрый сигнал о white screen / routing / critical boot regression;
- независимость от состояния dev-БД.

Полный browser e2e против живого backend можно расширять позже, когда auth/session edge cases и local-first runtime станут стабильнее.



### Почему Playwright должен быть удален из обязательного release-gates пути

Playwright несколько раз становился источником инфраструктурных blocker-сигналов: browser revision drift, отсутствующий `chromium_headless_shell` и timeout на install. Поэтому дальнейшая стратегия — не расширять Playwright-слой, а перенести цели browser smoke в кастомный runner:

- открыть UI в системном браузере;
- собрать DOM/console/storage/network evidence;
- проверить JS boot, router, actionable controls, form submit и state effects;
- запускать real-backend путь только против managed runtime/write-safe DB;
- удалить Playwright из deps/scripts/devbootstrap/docs только после acceptance parity.

## 9. Полезный минимальный сценарий перед коммитом

Если нужен короткий, но практичный local gate, достаточно пройти:

```bash
cd frontend
npm run test:run
```

```bash
cd backend
cargo test
```

```bash
cd backend
python tests/smoke_core_api.py
```

```bash
cd frontend
npm run test:browser
```

## 10. Что делать дальше

Следующее естественное развитие testing layer:

1. добавить frontend contract tests вокруг `docs/api/openapi.yaml`;
2. добавить integration tests для `WorkspaceBoardsPage`, `BoardPage`, `AuthPage`;
3. вынести reusable mocked API fixtures;
4. завести отдельные replayable sync/conflict scenario suites;
5. позже добавить CI job matrix для frontend/backend/browser smoke.
