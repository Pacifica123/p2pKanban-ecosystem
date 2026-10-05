# Тестовая БД и managed runtime для release gates

Пишущие проверки запрещены, пока не указан безопасный target. Это защищает
обычные dev-данные от smoke, DB integration tests и UIX real-backend flow.

## Рекомендуемый запуск

```bash
python tools/devbootstrap.py release-gates \
  --profile full-local-release \
  --test-db-retention=keep-on-failure
```

Профиль:

- подготавливает dependencies;
- создаёт отдельную PostgreSQL DB;
- запускает принадлежащие devbootstrap backend/frontend;
- выбирает свободные loopback-порты;
- подставляет CORS origin;
- выполняет UIX real-backend flow;
- запускает clean-machine dry sandbox;
- удаляет успешную test DB и сохраняет упавшую для диагностики.

## Профили согласия

```bash
python tools/devbootstrap.py release-gates --profile diagnostic --dry-run
python tools/devbootstrap.py release-gates --profile prepared-local
python tools/devbootstrap.py release-gates --profile isolated-db
python tools/devbootstrap.py release-gates --profile managed-runtime
python tools/devbootstrap.py release-gates --profile full-local-release --dry-run
```

Явные flags имеют приоритет над профилем. Каждый run записывает resolved
profile, разрешённые side effects и overrides в
`release-gates-consent.md/json`. Dry-run не создаёт БД, не ставит dependencies,
не запускает процессы и не копирует sandbox.

## Managed test DB

```bash
python tools/devbootstrap.py release-gates --managed-test-db
```

Создаётся БД вида:

```text
p2pkanban_rg_<tool-version>_<timestamp>_<id>
```

Все DB-writing gates получают переопределённые `DATABASE__URL`, `DATABASE_URL`
и `TEST_DATABASE_URL`.

Если обычный DB user не имеет `CREATEDB`, используйте отдельную admin role и
пароль из environment, чтобы пароль не попал в shell history:

```bash
export P2P_TEST_DB_ADMIN_PASSWORD='<password>'
python tools/devbootstrap.py release-gates \
  --profile full-local-release \
  --test-db-admin-user postgres \
  --test-db-admin-password-env P2P_TEST_DB_ADMIN_PASSWORD
```

PowerShell:

```powershell
$env:P2P_TEST_DB_ADMIN_PASSWORD = '<password>'
python tools/devbootstrap.py release-gates `
  --profile full-local-release `
  --test-db-admin-user postgres `
  --test-db-admin-password-env P2P_TEST_DB_ADMIN_PASSWORD
```

Политики хранения:

```text
drop-always
keep-on-failure
keep-always
```

По умолчанию используется `keep-on-failure`. При наличии `pg_dump` flag
`--dump-test-db-on-failure` сохраняет dump упавшего запуска.

## Managed runtime

`--managed-runtime` не доверяет случайным процессам на `18080` и `5173`. Он:

1. выбирает свободные порты;
2. запускает backend с test DB;
3. запускает frontend с правильным API URL;
4. ждёт health;
5. передаёт те же URLs smoke/UIX;
6. останавливает только свои PID.

Состояние и логи:

```text
logs/runtime-state.json
logs/runtime-env-diff.md
logs/managed-urls.env
logs/*managed_backend*.log
logs/*managed_frontend*.log
```

В env diff database URL и секреты маскируются.

## Ручная test DB

Если managed режим не подходит, создайте отдельную БД, например
`p2p_planner_test`, и задайте:

```bash
export TEST_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/p2p_planner_test
```

Backend для live smoke должен быть запущен против той же БД.

Два последовательных smoke намеренны:

```bash
cd backend
cargo test
TEST_DATABASE_URL=... cargo test -- --include-ignored
BASE_URL=http://127.0.0.1:18080/api/v1 TEST_DATABASE_URL=... python tests/smoke_core_api.py
BASE_URL=http://127.0.0.1:18080/api/v1 TEST_DATABASE_URL=... python tests/smoke_core_api.py
```

Второй прогон ловит неидемпотентные предположения.

## Clean-machine sandbox

Sandbox копирует проект во временный каталог без `.git`, `.dev-bootstrap`,
env, `node_modules`, `target`, `dist`, логов и release payload.

Профили:

| Профиль | Действия |
|---|---|
| `dry` | Required files, self-check, diagnose, plan, prepare-env, up dry-run |
| `deps` | `dry` + frontend prepare + `cargo test --no-run` |
| `runtime` | `deps` + вложенный managed release-gates |

По умолчанию успешный sandbox удаляется, а упавший сохраняется. Bundle содержит
report, JSON, file list, exclusions и command log.

## Dependencies

`--prepare-deps` поддерживает режимы:

- `never`;
- `missing`;
- `stale` / `missing-or-stale`;
- `always`.

Lockfile не изменяется неявно. Playwright browsers скачиваются только с
`--install-playwright-browsers`; без этого legacy browser gate может быть
пропущен как prerequisite.

`--allow-dev-db-write` разрешён только для заведомо одноразовой dev-БД.

