# Proposal: release-gates profiles and consent policy

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

## Смелая идея

Чтобы добавить managed DB, dependency install, runtime orchestration и clean-machine sandbox, не нужно плодить десятки команд. Нужна система профилей и единая consent policy: пользователь выбирает уровень смелости, а bootstrapper прозрачно показывает, какие side effects разрешены.

## Проблема

Сейчас release-gates уже имеет флаги вроде:

- `--prepare-frontend`;
- `--install-playwright-browsers`;
- `--include-real-backend-browser`;
- `--allow-dev-db-write`;
- `--include-clean-machine`.

Если добавить еще:

- `--managed-test-db`;
- `--managed-runtime`;
- `--prepare-deps`;
- `--keep-test-db`;
- `--start-db-if-needed`;
- `--dump-test-db-on-failure`;
- `--clean-machine-profile`;

то UX станет мощным, но перегруженным.

## Решение

Оставить низкоуровневые флаги для точной настройки, но добавить профили:

```bash
python tools/devbootstrap.py release-gates --profile diagnostic
python tools/devbootstrap.py release-gates --profile prepared-local
python tools/devbootstrap.py release-gates --profile isolated-db
python tools/devbootstrap.py release-gates --profile managed-runtime
python tools/devbootstrap.py release-gates --profile full-local-release
```

## Предлагаемые профили

| Profile | Side effects | Что запускает |
|---|---|---|
| `diagnostic` | none | self-check, diagnose, docs gates, prerequisite classification |
| `prepared-local` | npm ci if stale/missing, optional cargo fetch | frontend build/unit/browser mock, backend cargo default |
| `isolated-db` | create/drop test DB | DB Rust tests, Python smoke against managed/live backend depending config |
| `managed-runtime` | start/stop backend/frontend processes | Python smoke and browser against owned runtime |
| `full-local-release` | prepare deps + managed DB + managed runtime + optional clean-machine | Максимальный локальный сигнал |

## Consent categories

Вместо хаоса флагов каждый side effect попадает в категорию:

| Category | Examples | Default |
|---|---|---|
| `write-project-cache` | `node_modules`, Playwright browser cache, Cargo cache | allowed by prepared profiles |
| `write-project-files` | `.env`, lockfiles, source files | denied by release-gates |
| `write-database` | smoke/API writes | allowed only to managed/test DB или explicit allow-dev-db-write |
| `create-database` | `createdb` | only with managed DB/profile |
| `delete-database` | `dropdb` | only DB from current managed registry |
| `start-process` | backend/frontend | only managed-runtime/profile |
| `stop-process` | backend/frontend | only tracked processes |
| `network-download` | npm/cargo/playwright | explicit or profile-driven with log |

## UX: consent summary before destructive work

В interactive terminal можно показать план:

```text
release-gates profile: full-local-release
Allowed side effects:
- install frontend deps with npm ci if missing/stale
- create PostgreSQL test DB p2pkanban_rg_...
- start backend/frontend on dynamic ports
- write test data only to managed DB
- drop managed DB on success, keep on failure
Denied side effects:
- no writes to source files or lockfiles
- no writes to dev DB
- no killing foreign processes
```

Для non-interactive режима этот план пишется в bundle, а команда выполняется только если профиль явно задан.

## Dry-run

Каждый profile должен поддерживать:

```bash
python tools/devbootstrap.py release-gates --profile full-local-release --dry-run
```

Dry-run обязан показать:

- какие gates будут добавлены;
- какие prerequisites нужны;
- какие side effects были бы разрешены;
- какие команды могли бы быть выполнены;
- какие env vars нужны;
- какие части сейчас точно impossible.

Dry-run не должен:

- создавать БД;
- ставить зависимости;
- стартовать процессы;
- писать env files;
- делать network downloads.

## Как флаги конфликтуют с профилями

Правило:

```text
profile задает defaults, explicit flags override profile
```

Примеры:

```bash
# full profile, но БД сохранить всегда
release-gates --profile full-local-release --test-db-retention=keep-always

# prepared-local, но без browser download
release-gates --profile prepared-local --install-playwright-browsers=false

# diagnostic, но включить clean-machine dry
release-gates --profile diagnostic --include-clean-machine
```

## Риски и смягчения

| Риск | Последствие | Смягчение |
|---|---|---|
| Пользователь не понимает side effects | Недоверие к tool | Consent summary + dry-run |
| Профили скрывают детали | Трудно debug | Bundle содержит expanded resolved plan |
| Слишком много флагов | UX распадается | Profiles first, flags only for override |
| Опасный default | Потеря данных | Default profile remains `diagnostic` or current safe behavior |
| CI needs strictness | Неожиданные installs | `--profile ci-strict`/`--prepare-deps=never` future |

## Рекомендуемый rollout

1. Сначала ввести `--profile diagnostic` как alias текущего безопасного поведения.
2. Затем `--profile prepared-local` для dependency prepare.
3. Потом `--profile isolated-db`.
4. Потом `--profile managed-runtime`.
5. Только после этого `--profile full-local-release`.

## Definition of done

- Пользователь может запустить понятный профиль вместо набора из 6-8 флагов.
- Summary показывает expanded plan и side effects.
- Dry-run профиля ничего не меняет.
- Все dangerous actions требуют либо managed ownership, либо explicit opt-in.
