# Каталог проблем развёртывания

Этот каталог помогает сначала определить класс сбоя, а уже потом менять код.
Подробные логи должны находиться в конкретном run bundle.

## Карта проблем

| Слой | Типичные причины | Категория |
|---|---|---|
| ОС | Права, длина пути, shell, часы | `REL-ENV` |
| Структура проекта | Неверный cwd, нет backend/frontend/tools | discovery failure |
| Python | Не найден или несовместим | prerequisite |
| Git/devctl | Dirty tree, нет patches, push failure | `REL-DEVCTL` |
| Rust | Нет toolchain, ошибка metadata/check/test/linker | `REL-BE` или infra |
| Node/npm | Нет npm, lock mismatch, install failure | `REL-FE` |
| PostgreSQL | Сервис выключен, пароль/роль/БД неверны | `REL-DB` |
| Backend runtime | Порт, env, миграции, health timeout | `REL-PROC` / `REL-BE` |
| Frontend runtime | Vite, API URL, порт | `REL-FE` / `REL-PROC` |
| UIX | Браузер, JS, route marker, form/storage/network | `REL-UIUX` |
| Smoke | Общая грязная БД, неидемпотентность | `REL-SMOKE` |
| Cleanup | Чужой PID, старое состояние | `REL-PROC` |
| Архив | Generated/secret файлы в source | `REL-DEVCTL` / `REL-SEC` |

## Правила диагностики

1. Отделять ошибку среды от регрессии продукта.
2. Сохранять raw output, удаляя секреты.
3. Не писать в общую БД «для проверки».
4. Не убивать процесс только потому, что он занял ожидаемый порт.
5. Давать одну короткую команду повторного запуска.
6. Не хранить `.dev-bootstrap` как исходный код.

## PostgreSQL

Проверять по порядку:

- доступен ли `pg_isready`;
- тот ли host/port;
- проходит ли authentication;
- существует ли нужная БД;
- disposable ли она;
- может ли admin создать отдельную test DB;
- использует ли backend именно эту БД;
- применились ли миграции.

Обычный пользовательский bootstrap изолирует PostgreSQL внутри Docker и снимает
большинство этих проблем. Этот список нужен главным образом для host-native
разработки и release gates.

## UI

Нужно различать:

- браузер отсутствует;
- frontend недоступен;
- приложение не смонтировалось;
- fatal в console;
- route marker отсутствует;
- кнопка скрыта или disabled;
- отправка формы не прошла;
- storage повреждён;
- backend ответил несовместимым контрактом.

## Архив

В project/release snapshot не должны попадать:

```text
.git/
.devctl/
.dev-bootstrap/
.venv/
node_modules/
target/
dist/
build/
coverage/
logs/
__pycache__/
.pytest_cache/
.env*
*.db
*.sqlite
*.tsbuildinfo
```

