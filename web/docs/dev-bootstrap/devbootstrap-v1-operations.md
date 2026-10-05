# Работа с devbootstrap

`tools/devbootstrap.py` нужен разработчикам и release manager. Для обычного
self-host запуска используйте `python bootstrap.py`.

## Безопасная последовательность

```bash
python tools/devbootstrap.py self-check
python tools/devbootstrap.py diagnose
python tools/devbootstrap.py plan
python tools/devbootstrap.py up --dry-run
python tools/devbootstrap.py up
python tools/devbootstrap.py smoke --level quick
python tools/devbootstrap.py status
python tools/devbootstrap.py stop
```

`standard` и `full` smoke могут писать через backend API. Предпочтителен
`TEST_DATABASE_URL`; `--allow-dev-db-write` допустим только для заведомо
одноразовой dev-БД.

## Команды

| Команда | Действие | Безопасность по умолчанию |
|---|---|---|
| `self-check` | Проверяет внутренние fixtures и contracts | Да |
| `diagnose` | Читает инструменты, файлы, порты и health | Да |
| `plan` | Сравнивает examples и env, маскируя секреты | Да |
| `prepare-env` | Создаёт только отсутствующие env | Да |
| `start-db` | Проверяет/запускает dev PostgreSQL | С защитой |
| `check-backend` | Выполняет Cargo metadata/check | Да |
| `start-backend` | Запускает однозначный backend binary | С защитой |
| `prepare-frontend` | Выполняет npm install policy | С защитой |
| `start-frontend` | Запускает Vite и хранит PID/log | С защитой |
| `up` | Собирает шаги в один pipeline | Сначала `--dry-run` |
| `smoke` | Quick/standard/full | Запись только с согласием |
| `status` | Показывает tracked state | Да |
| `stop` | Останавливает только свои процессы | Да |

Backend всегда запускается явно:

```bash
cargo run --bin p2p-planner-backend
```

Это важно после появления второго binary `nostr_recover`.

## Результаты

Каждый пишущий запуск создаёт:

```text
.dev-bootstrap/runs/YYYYMMDD_HHMMSS_<command>/
  report.md
  <command>.json
  *.log
```

JSON имеет общую оболочку `schemaVersion`, `command`, `toolVersion`,
`generatedAt`, `status`. Значения с признаками `SECRET`, `PASSWORD`, `TOKEN`,
`COOKIE` и database URL маскируются.

## Ошибки

Каждый сбой должен отвечать:

1. какая команда упала;
2. какой это subsystem;
3. ошибка среды это или продукта;
4. что запустить дальше.

Примеры:

- `port_conflict` — чужой процесс не убивается автоматически;
- `migration_drift` — проверить sqlx/build artifacts;
- `postgres_auth_failed` — порт открыт, но роль/пароль/БД не совпали;
- `frontend_dependency_missing` — восстановить npm dependencies;
- `runtime_unreachable` — smoke не достиг сервиса.

## Cleanup

`stop` читает `.dev-bootstrap/state.json`, проверяет ownership PID и не трогает
произвольные процессы. PostgreSQL останавливается только с `--include-db`.
Volumes не удаляются.

## Проверка самого инструмента

```bash
python -B tools/devbootstrap.py self-check --no-write-report
python -B tools/devbootstrap.py diagnose --no-write-report
python -B tools/devbootstrap.py up --dry-run --smoke-level quick
python -B tools/devbootstrap.py stop --dry-run --no-write-report
```

