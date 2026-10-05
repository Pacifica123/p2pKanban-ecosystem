# Project code follow-up plan from release-gates 2026-05-24

## Источник анализа

Документ построен по результатам архива `20260524_200616_release-gates.zip` для запуска `20260524_200616_release-gates`.

Фактический итог прогона:

- overall: `infra_failed`;
- classification: `release_gates_infra_failed`;
- `self_check` и `diagnose` прошли;
- `cargo test` завершился кодом `0`, но release-gates классифицировал его как `partial_pass / critical_tests_ignored`, потому что DB-зависимые Rust-тесты были `ignored`;
- `cargo test -- --include-ignored` был пропущен из-за отсутствия `TEST_DATABASE_URL` и безопасного DB-target;
- два Python smoke-прогона были пропущены защитой от записи в live/dev DB;
- `npm run build`, `npm run test:run`, `npm run test:browser` не стартовали из-за отсутствующего `frontend/node_modules`;
- `npm run test:browser:real-backend` был пропущен, потому что write-capable real-backend gate требует явного opt-in и безопасной DB;
- docs gates прошли, clean-machine quickstart был optional и не запускался.

Ключевой вывод: этот прогон не доказал regression в продуктовой логике backend/frontend. Он доказал, что release-gates пока слишком часто останавливается на подготовке окружения и ручных prerequisite-действиях.

## Короткий вердикт

По этому конкретному прогону нельзя честно сказать, что frontend или backend код сломан. Большинство release-critical проверок не дошло до выполнения из-за prerequisites.

Но прогон показал, какие доработки backend/frontend кода и тестового surface нужны, чтобы следующий release-gates давал не `unknown`, а доказательный сигнал.

## Что уже выглядит нормально

1. `self_check` прошел: базовые fixtures devbootstrap работают.
2. `diagnose` прошел: required files на месте, backend health endpoints отвечают.
3. `cargo test` скомпилировал backend и выполнил хотя бы non-DB тест `health_endpoint_is_still_wired`.
4. Docs gates прошли: README/release notes/v1 checklist содержат обязательные fragments.
5. Наличие `backend/build.rs` подтверждено diagnose; это важно для `sqlx::migrate!()` и миграционного drift.

## Что осталось непроверенным

| Зона | Почему не проверена |
|---|---|
| Backend DB integration tests | `TEST_DATABASE_URL` отсутствовал, ignored tests не запускались |
| Python backend smoke | write guard не разрешил запись в live/dev DB |
| Frontend build | `frontend/node_modules` отсутствует |
| Frontend unit/integration tests | `frontend/node_modules` отсутствует |
| Mocked browser smoke | `frontend/node_modules` отсутствует |
| Real-backend browser smoke | Нужны explicit opt-in и write-safe DB |
| Clean-machine quickstart | Optional flag не был включен |

## Backend: план доработки кода и тестового surface

### 1. Сделать DB integration tests менее «невидимыми»

Проблема: `cargo test` завершился `0`, но release-gates справедливо отметил `critical_tests_ignored`. Человеку легко пропустить, что важные тесты не запускались.

План:

- Вынести общий helper `require_test_database()` в `backend/tests/support`.
- Все DB-зависимые Rust tests должны печатать одинаковую причину skip/ignore.
- Добавить отдельный быстрый тест, который проверяет наличие миграций и test fixtures без подключения к DB.
- В docs/tests явно разделить:
  - pure unit/health tests;
  - DB integration tests;
  - smoke/API tests.

Критерий готовности:

```bash
cd backend
cargo test
TEST_DATABASE_URL=... cargo test -- --include-ignored
```

Первый прогон не должен считаться полноценным release signal, второй должен реально запускать DB cases.

### 2. Изолировать тестовые данные backend smoke

Проблема: Python smoke пишет через API и поэтому правильно требует безопасную БД. При shared dev DB smoke может быть неидемпотентным или зависеть от старого состояния пользователя.

План:

- Каждый smoke run должен использовать уникальный namespace:
  - unique user email suffix;
  - unique workspace/board/card names;
  - run id in test data.
- Cleanup должен удалять или архивировать все созданные сущности, но smoke не должен падать, если cleanup частично невозможен.
- Пользовательские настройки вроде `me/appearance` нельзя проверять через fixed user default в общей DB; default-state checks должны жить в isolated DB integration test.
- Добавить smoke summary с количеством созданных/удаленных entities.

Критерий готовности:

```bash
BASE_URL=... TEST_DATABASE_URL=... python backend/tests/smoke_core_api.py
BASE_URL=... TEST_DATABASE_URL=... python backend/tests/smoke_core_api.py
```

Два подряд прогона должны проходить на одной test DB.

### 3. Расширить backend smoke coverage по уже реализованному surface

Текущий проект уже содержит modules для core CRUD, auth/session, appearance, activity/audit, labels, checklists, comments, sync/import-export pieces. Release-gates должен постепенно доказывать не только health/core.

Приоритеты:

1. Auth/session:
   - sign-up/sign-in;
   - wrong token;
   - refresh/logout behavior, если endpoint готов;
   - отсутствие legacy `X-User-Id` как обязательного happy path.
2. Core kanban:
   - workspace → board → columns → cards;
   - reorder/move card;
   - archive/delete semantics.
3. Permissions:
   - второй пользователь не видит private workspace;
   - member roles ограничивают mutation;
   - board/card access checked consistently.
4. Appearance:
   - default values in isolated DB;
   - partial update;
   - invalid preset/theme/wallpaper → `400`, not `500`.
5. Activity/audit:
   - mutation creates activity entry;
   - board activity/card activity/audit-log return deterministic newest-first order;
   - permission cases.
6. Labels/checklists/comments:
   - если это уже кодово заведено, добавить smoke для happy path;
   - если не готово, зафиксировать как not release-critical или feature-flagged.

### 4. Добавить migration rehearsal fixtures

Проблема: release-gates проверяет текущую БД только когда она есть. Но будущий пользователь будет обновляться с версии N на N+1, и это отдельный риск.

План:

- Хранить минимальный SQL fixture или seed script для «данные предыдущей версии».
- На managed test DB прогонять:
  - create DB;
  - apply migrations;
  - load/verify fixture;
  - run invariant checks.
- Для будущих версий добавить migration compatibility notes.

Критерий готовности:

- Есть отдельный gate `backend_migration_rehearsal`.
- Он падает на schema drift, missing migration, broken invariant.

### 5. Проверить error contract

Чтобы frontend был устойчивым, backend должен возвращать предсказуемые errors.

План:

- Для основных endpoints закрепить формат:

```json
{
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

- Smoke должен проверять не только status code, но и `error.code` для unauthorized/validation/not_found/forbidden.
- OpenAPI должен соответствовать реальному error surface.

## Frontend: план доработки кода и тестового surface

### 1. Сначала добиться реального запуска frontend gates

Пока `node_modules` отсутствует, невозможно доказать, что код frontend собирается.

План для кода/проектовой структуры:

- Сохранить strict `npm ci` через lockfile.
- Не добавлять generated `node_modules` в архив/патчи.
- Проверить, что `npm run build` не требует скрытых local files.
- Проверить, что `vite.config.ts/js` не расходятся по смыслу. Если оба нужны из-за compiled artifact, это должно быть описано; если нет — оставить один источник правды в будущей уборке.

Критерий готовности:

```bash
cd frontend
npm ci
npm run build
npm run test:run
npm run test:browser
```

### 2. Укрепить browser smoke селекторы

Browser smoke должен проверять пользовательский путь, а не случайные тексты, которые могут дублироваться в heading/link/card.

План:

- Добавить стабильные `data-testid`/accessible names для:
  - auth page;
  - workspace list;
  - create workspace form;
  - board link;
  - card creation;
  - card drawer/details.
- Не использовать strict `getByText`, если один и тот же текст закономерно появляется в нескольких местах.
- Для smoke выбирать role-based locators там, где UI semantics stable.

Критерий готовности:

- Mocked browser smoke проходит после `npm ci`.
- Тест не ломается от появления heading + link с одинаковым названием workspace.

### 3. Развести mocked browser smoke и real-backend browser smoke

Проблема: mocked browser smoke полезен для UI, но не доказывает API wiring. Real-backend smoke полезен, но опасен без write-safe DB.

План:

- Mocked smoke проверяет UI contract без backend.
- Real-backend smoke:
  - использует `VITE_API_BASE_URL`/env текущего managed backend;
  - создает уникальные данные;
  - не полагается на dev DB;
  - проверяет минимум: login/session → workspace list/create → board open → card create/update.
- В test names явно писать `mocked` vs `real-backend`.

Критерий готовности:

```bash
npm run test:browser
VITE_API_BASE_URL=... npm run test:browser:real-backend
```

### 4. Улучшить frontend обработку auth/error/loading states

Поскольку backend уже возвращает `401` для anonymous `/workspaces`, frontend должен явно и стабильно обрабатывать auth boundary.

План:

- Auth/session provider должен иметь states:
  - loading;
  - anonymous;
  - authenticated;
  - expired/invalid token.
- API client должен нормализовать backend error payload.
- Pages должны показывать ErrorState/EmptyState без crash при `401/403/404/500`.
- Unit/integration tests должны покрывать хотя бы:
  - anonymous redirect/auth page;
  - workspace empty state;
  - API error state;
  - successful workspace render.

### 5. Подключить frontend к уже реализованным backend surfaces по приоритету

План по очередности:

1. Core board flow: workspace/boards/columns/cards.
2. Card details drawer with comments/checklists/labels only если backend surface подтвержден smoke-тестом.
3. Appearance pages: user appearance + board appearance.
4. Activity feed/card history/audit log read-only UI.
5. Sync/local-first banners только как honest status, без обещания полной offline sync раньше backend readiness.

Критерий готовности:

- Для каждой подключенной feature есть минимум один integration/unit test или browser smoke step.
- Недоведенные features скрыты feature flag / disabled state / known limitation, а не выглядят как fully ready.

### 6. Contract parity для frontend types

Проблема: frontend может разойтись с OpenAPI/backend DTO, а текущий прогон этого не проверил.

План:

- Добавить contract parity check между `docs/api/openapi.yaml` и frontend API client assumptions.
- Для ключевых DTO иметь fixtures:
  - workspace;
  - board;
  - column;
  - card;
  - activity entry;
  - appearance settings;
  - error payload.
- Unit tests API client должны проверять normalize/parse paths.

## Общий порядок реализации

### Step 1: закрыть infra blockers

Это формально относится к bootstrapper, но без этого code work невозможно проверить:

```bash
python tools/devbootstrap.py release-gates --prepare-frontend
# или future:
python tools/devbootstrap.py release-gates --profile prepared-local
```

И отдельно DB:

```bash
# сейчас вручную по docs/dev-bootstrap/release-gates-test-database.md
# future: --managed-test-db
```

### Step 2: backend DB/smoke reliability

- Уникальные smoke данные.
- Два последовательных smoke-прогона.
- Permission/validation coverage.

### Step 3: frontend build/test/browser signal

- Стабильные selectors.
- Integration tests for auth/workspace/core board.
- Real-backend browser smoke только against safe DB/runtime.

### Step 4: feature coverage expansion

- appearance;
- activity/audit;
- comments/checklists/labels if release-critical;
- migration rehearsal.

## Не делать пока

- Не чинить «frontend failure» вслепую, пока build/test вообще не запускались.
- Не считать `cargo test` без include-ignored достаточным backend release signal.
- Не включать `--allow-dev-db-write` как default.
- Не добавлять destructive test endpoints в production build.
- Не превращать frontend smoke в огромный e2e suite: smoke должен оставаться коротким и диагностичным.

## Definition of done for next release-gates run

Следующий качественный прогон должен показать:

- `cargo test`: passed без critical hidden ignored surprise или clearly classified partial;
- `cargo test -- --include-ignored`: реально executed against test DB;
- Python smoke first/second: passed against write-safe DB;
- `npm run build`: passed;
- `npm run test:run`: passed;
- `npm run test:browser`: passed;
- `npm run test:browser:real-backend`: passed when explicitly included against safe DB/runtime;
- clean-machine quickstart: at least dry mode passed for release review.

Только после этого можно переходить от формулировки «infra blockers мешают проверить продукт» к честному выводу о состоянии backend/frontend кода.
