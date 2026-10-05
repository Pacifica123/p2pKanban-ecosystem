# Proposal: managed ephemeral test database for release-gates

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

`devbootstrap release-gates` должен уметь сам создавать write-safe PostgreSQL database для конкретного прогона, запускать против нее DB integration tests, Python smoke и real-backend browser smoke, а затем по понятной политике либо удалить ее, либо сохранить для расследования.

Рабочая формула:

```text
release-gates
→ обнаружить PostgreSQL capability
→ создать одноразовую БД p2pkanban_rg_<toolVersion>_<YYYYMMDD_HHMMSS>_<shortId>
→ запустить миграции и backend against that DB
→ выполнить DB-writing gates
→ собрать дамп/метаданные при необходимости
→ drop или keep по retention policy
```

## Почему это нужно

Текущий прогон показал сразу три слабых места:

1. DB integration tests существуют, но обычный `cargo test` дает ложное ощущение успеха: часть важных тестов игнорируется.
2. Python smoke и real-backend browser smoke правильно защищены от записи в dev DB, но из-за этого часто не запускаются вообще.
3. Человеку приходится вручную создать БД, выставить `TEST_DATABASE_URL`, перезапустить backend и не забыть cleanup.

Идеальная release-проверка должна быть write-safe по умолчанию, а не требовать от пользователя вручную подготовить «правильную» БД.

## Целевой UX

Базовый сценарий:

```bash
python tools/devbootstrap.py release-gates --managed-test-db
```

Удобный release-сценарий:

```bash
python tools/devbootstrap.py release-gates --prepare-frontend --managed-test-db --include-real-backend-browser
```

Сохранить БД после падения:

```bash
python tools/devbootstrap.py release-gates --managed-test-db --keep-test-db=on-failure
```

Политика хранения:

```bash
python tools/devbootstrap.py release-gates --managed-test-db --test-db-retention=drop-always|keep-on-failure|keep-always
```

Важно: это не должно плодить десяток новых команд. Нужен один флаг capability (`--managed-test-db`) и один компактный retention flag.

## Алгоритм

1. Выполнить preflight PostgreSQL:
   - есть ли `psql`, `createdb`, `dropdb`, `pg_isready`;
   - открыт ли порт из `DATABASE__URL`, `DATABASE_URL` или compose default;
   - доступен ли Docker compose service `postgres`, если локальный PostgreSQL не найден;
   - можно ли подключиться к maintenance DB (`postgres` по умолчанию);
   - есть ли privilege на `CREATE DATABASE`.
2. Сформировать имя БД:
   - только ASCII, lowercase, underscore;
   - включить toolVersion/run timestamp/short random id;
   - пример: `p2pkanban_rg_2_0_0_draft_20260524_200616_a1b2c3`.
3. Создать БД через один из backend-ов:
   - native `createdb`;
   - `psql -c "CREATE DATABASE ..."`;
   - `docker exec <postgres-container> createdb ...`, если DB поднята compose-сервисом.
4. Сформировать `TEST_DATABASE_URL` и временный `DATABASE__URL` для managed backend process.
5. Запустить backend/migrations against managed DB.
6. Запустить gates:
   - `cargo test -- --include-ignored`;
   - `python tests/smoke_core_api.py` два раза;
   - `npm run test:browser:real-backend`, если включен.
7. После gates выполнить retention decision:
   - `drop-always`: удалить всегда, но сначала записать имя БД и summary;
   - `keep-on-failure`: удалить только при полном успехе;
   - `keep-always`: сохранить и явно напечатать команду удаления.
8. В release-gates bundle положить:
   - database name;
   - created URL без секрета;
   - migration status;
   - retention decision;
   - cleanup command;
   - список gates, которые реально использовали managed DB.

## Linux / Windows / Docker различия

### Linux native PostgreSQL

Плюсы:

- `createdb/dropdb/psql` обычно доступны через пакет PostgreSQL client;
- проще всего быстро проверить capability.

Риски:

- пользователь может иметь client tools, но не иметь server;
- socket/host auth может отличаться от `127.0.0.1`;
- роль пользователя может не иметь `CREATEDB`.

Поведение:

- если нет privilege, не пытаться «чинить» PostgreSQL;
- показать конкретный next action: использовать compose postgres или создать role вручную;
- не просить пароль интерактивно внутри release-gates, если command должен быть воспроизводимым.

### Windows native PostgreSQL

Риски выше:

- tools могут быть не в `PATH`;
- service может называться иначе;
- quoting database name/URL часто ломается в shell;
- `createdb.exe` может быть установлен, но server не запущен.

Поведение:

- предпочесть Python `subprocess` с аргументами list, без shell string;
- явно диагностировать missing `createdb.exe/psql.exe`;
- рекомендовать Docker compose path как более воспроизводимый;
- не пытаться устанавливать PostgreSQL автоматически.

### Docker compose PostgreSQL

Плюсы:

- проект уже содержит `docker-compose.dev.yml`;
- containerized path более одинаковый на Windows/Linux;
- проще сделать безопасную disposable DB.

Риски:

- Docker Desktop может быть не запущен;
- compose binary может называться `docker compose` или `docker-compose`;
- container может быть поднят не этим проектом;
- пользователь может не хотеть стартовать DB автоматически.

Поведение:

- `--managed-test-db` может предложить `--start-db-if-needed`, но не должен без спроса стартовать Docker на обычном dry-run;
- если container найден по compose project/service, использовать его;
- если найден чужой PostgreSQL на порту, не считать его автоматически disposable.

## Drop или keep?

Рекомендуемая политика по умолчанию для `--managed-test-db`:

```text
success  → drop
failure  → keep-on-failure
manual interrupt → keep-on-failure
```

Почему не `drop-always` по умолчанию:

- при падении теста нужна возможность посмотреть состояние данных;
- dropped DB делает расследование сложнее;
- итоговый bundle может содержать только логи, но не фактическую БД.

Почему не `keep-always`:

- легко накопить десятки БД;
- пользователь забудет cleanup;
- на Windows/Docker это быстро превращается в «мусорное окружение».

Нужен отдельный cleanup summary:

```text
Kept test database: p2pkanban_rg_...
Reason: release gates failed at backend_python_smoke_second
Cleanup: dropdb -h 127.0.0.1 -p 5432 -U postgres p2pkanban_rg_...
```

## Как не потерять пользовательские данные

Запрещенные действия:

- не использовать `DATABASE__URL` как target для destructive reset без явного `--allow-dev-db-write`;
- не делать `DROP DATABASE` для имени, которое не создано текущим run id;
- не чистить database по prefix без отдельного explicit cleanup mode;
- не делать `TRUNCATE` в dev DB.

Безопасный признак ownership:

- имя БД содержит run id;
- в bundle есть metadata file `.dev-bootstrap/runs/<id>/managed-test-db.json`;
- cleanup удаляет только DB из metadata текущего run или из registry старых managed DB.

## Если БД надо сохранить и мигрировать

Это важный мост к будущему пользовательскому обновлению данных.

Для test DB:

- `keep-on-failure` сохраняет DB для расследования;
- `release-gates db export` как отдельная будущая подкоманда не обязательна сразу, но bundle должен хранить рекомендуемую `pg_dump` команду;
- полезно иметь `--dump-test-db-on-failure`, который кладет сжатый dump в run directory, но не в обычный маленький bundle по умолчанию.

Для будущей пользовательской миграции:

1. Перед обновлением приложения делать backup/export текущей пользовательской БД.
2. Запускать миграции в транзакционном режиме, где это возможно.
3. После миграции запускать read-only health/invariant checks.
4. При провале давать пользователю понятный путь rollback через backup.
5. В release-gates добавить отдельный future gate `migration-rehearsal`:
   - создать DB версии N;
   - загрузить fixture/snapshot;
   - применить миграции версии N+1;
   - проверить invariants.

Идея managed ephemeral DB хорошо готовит этот будущий сценарий: release-gates начнет регулярно доказывать, что проект умеет безопасно создавать, мигрировать и уничтожать isolated data target.

## Риски и смягчения

| Риск | Последствие | Смягчение |
|---|---|---|
| Нет PostgreSQL | DB gates снова skipped | Четкая classification `postgres_missing`, next action: compose/native setup |
| Нет `CREATEDB` privilege | Managed DB не создать | Classification `postgres_createdb_permission_denied`, предложить compose postgres или роль с CREATEDB |
| Неправильный URL | Smoke бьет в dev DB | Managed process должен явно override `DATABASE__URL`; bundle печатает masked target |
| Drop не той БД | Потеря данных | Drop только БД из managed registry текущего run, prefix alone недостаточен |
| DB осталась после падения | Мусор | Registry + команда cleanup + future `release-gates cleanup-managed-dbs --older-than` |
| Windows quoting | Невоспроизводимые ошибки | subprocess list args, без shell interpolation |
| Docker не запущен | Infra fail | Не пытаться лечить, дать точный next action |

## Этапы реализации

### Phase A: capability detection only

- Добавить preflight, который говорит: можно/нельзя создать managed DB и почему.
- Ничего не создавать без `--managed-test-db`.

### Phase B: create/drop lifecycle

- Реализовать create/drop и metadata registry.
- Запускать только `cargo test -- --include-ignored` against managed DB.

### Phase C: managed backend process

- Стартовать backend на managed DB для Python smoke и real-backend browser.
- Не использовать уже запущенный чужой backend для write gates.

### Phase D: retention and migration rehearsal

- Добавить keep/drop policy.
- Добавить optional dump-on-failure.
- Добавить fixture-based migration rehearsal gate.

## Definition of done

- Без `--managed-test-db` поведение остается безопасным и совместимым.
- С `--managed-test-db` DB-writing gates не skipped при наличии PostgreSQL capability.
- В summary видно имя БД, masked URL, retention decision и cleanup command.
- Нельзя удалить БД, не созданную текущим managed run.
- На Windows/Linux/Docker failures классифицируются разными понятными кодами, а не одним общим `infra_failed`.
