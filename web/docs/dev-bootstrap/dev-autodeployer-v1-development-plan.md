# План devbootstrap v1

- Статус: план реализован и расширен; документ сохранён как короткая справка

`tools/devbootstrap.py` — проектный помощник для разработки и release gates. Он
диагностирует host-native окружение, запускает принадлежащие ему процессы и
собирает доказательства. Обычный конечный пользователь должен запускать
`bootstrap.py`, а не проходить этот план.

## Границы

Devbootstrap:

- не является package manager;
- не скрывает разрушительные действия;
- не пишет молча в общую БД;
- не останавливает чужие процессы;
- не заменяет devctl;
- использует только стандартную библиотеку Python.

## Основные команды

| Команда | Назначение |
|---|---|
| `diagnose` | Read-only проверка платформы, инструментов, портов и HTTP |
| `plan` | План env/runtime действий |
| `prepare-env` | Создать только отсутствующие env из examples |
| `start-db` | Защищённая помощь с dev PostgreSQL |
| `check-backend` | Cargo metadata/check |
| `prepare-frontend` | Установка зависимостей по выбранной политике |
| `up` | Управляемый host-native запуск |
| `smoke` | Quick/standard/full проверки |
| `status` / `stop` | Состояние и остановка только своих процессов |
| `release-gates` | Keep-going релизный прогон и bundle |
| `self-check` | Внутренние fixtures самого инструмента |

## Что уже реализовано

- JSON/Markdown reports;
- timeout и классификация ошибок;
- Windows resolution для `.cmd`;
- managed test DB;
- managed backend/frontend на динамических портах;
- контроль frontend dependencies;
- consent profiles;
- remediation bundle, ledgers, scorecard и regression memory;
- UIX runner без обязательного скачивания Playwright browser.

## Generated состояние

Все результаты находятся в `.dev-bootstrap/`, например:

```text
.dev-bootstrap/state.json
.dev-bootstrap/frontend-install.json
.dev-bootstrap/runs/<run-id>/report.md
.dev-bootstrap/runs/<run-id>/release-gates.json
.dev-bootstrap/runs/<run-id>/release-gates_*.zip
```

Этот каталог не входит в devctl snapshots и релизный ZIP.

## Модель безопасности

- чтение среды разрешено;
- reports можно писать только в `.dev-bootstrap`;
- существующие env не перезаписываются;
- dependency install требует явного профиля;
- DB-writing требует managed test DB или отдельного согласия;
- запускаются и останавливаются только tracked owned processes;
- Docker volumes не удаляются неявно.

