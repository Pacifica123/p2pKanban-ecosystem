# PostgreSQL backup и контролируемое восстановление

- Статус: runbook для zero-config Docker bootstrap
- Актуально на: 2026-07-29
- Compose project: `p2pkanban-bootstrap`

Этот runbook дополняет прикладной JSON export. PostgreSQL dump сохраняет всю
БД, включая аккаунты, права, activity и служебное состояние.

Восстановление удаляет текущую БД. Сначала отработайте сценарий на тестовой
копии и храните backup вне каталога проекта.

## Автоматический backup перед update

`python bootstrap.py update` и `python bootstrap.py rollback` создают custom
dump до переключения:

```text
.dev-bootstrap/backups/<operation-id>/p2pkanban.dump
.dev-bootstrap/backups/<operation-id>/manifest.json
```

Manifest содержит SHA-256 и counts пользователей, workspace, досок и карточек.
Updater не восстанавливает dump автоматически.

## Ручной backup без обновления

Из корня активного проекта:

```bash
mkdir -p .dev-bootstrap/manual-backups

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres sh -lc \
  'pg_dump --username p2pkanban --dbname p2pkanban --format=custom --no-owner --no-privileges --file=/tmp/p2pkanban-manual.dump'

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  cp postgres:/tmp/p2pkanban-manual.dump \
  .dev-bootstrap/manual-backups/p2pkanban-manual.dump

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres rm -f /tmp/p2pkanban-manual.dump
```

На PowerShell создайте каталог через:

```powershell
New-Item -ItemType Directory -Force .dev-bootstrap/manual-backups
```

Остальные команды `docker compose` работают без бинарного перенаправления и
потому безопасны для custom dump на обеих платформах.

## Проверка backup

Скопируйте dump во временный каталог контейнера и прочитайте каталог архива:

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  cp .dev-bootstrap/manual-backups/p2pkanban-manual.dump \
  postgres:/tmp/p2pkanban-verify.dump

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres pg_restore --list /tmp/p2pkanban-verify.dump

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres rm -f /tmp/p2pkanban-verify.dump
```

Пустой файл, ошибка `pg_restore --list` или несовпадающий SHA-256 означает,
что backup нельзя считать проверенным.

## Restore drill

### 1. Зафиксировать counts

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres psql \
  --username p2pkanban \
  --dbname p2pkanban \
  --tuples-only \
  --no-align \
  --command "select json_build_object('users',(select count(*) from users),'workspaces',(select count(*) from workspaces),'boards',(select count(*) from boards),'cards',(select count(*) from cards))::text;"
```

Сохраните результат рядом с dump.

### 2. Создать отдельный safety backup

Непосредственно перед restore повторите ручной backup под другим именем. Не
восстанавливайте единственную копию поверх единственной рабочей БД.

### 3. Остановить приложения, оставив PostgreSQL

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  stop backend web
```

### 4. Проверить и скопировать выбранный dump

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  cp /absolute/path/to/p2pkanban.dump postgres:/tmp/p2pkanban-restore.dump

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres pg_restore --list /tmp/p2pkanban-restore.dump
```

### 5. Пересоздать БД

Это разрушительный шаг:

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres psql \
  --username p2pkanban \
  --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --command "select pg_terminate_backend(pid) from pg_stat_activity where datname = 'p2pkanban' and pid <> pg_backend_pid();" \
  --command "drop database if exists p2pkanban;" \
  --command "create database p2pkanban owner p2pkanban;"
```

### 6. Восстановить dump

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres pg_restore \
  --username p2pkanban \
  --dbname p2pkanban \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  /tmp/p2pkanban-restore.dump

docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  exec -T postgres rm -f /tmp/p2pkanban-restore.dump
```

### 7. Запустить и проверить

```bash
python bootstrap.py
```

После readiness:

1. повторите запрос counts;
2. войдите прежним аккаунтом;
3. откройте контрольную доску и карточку;
4. создайте тестовую карточку;
5. выполните `python bootstrap.py stop`, затем `python bootstrap.py`;
6. убедитесь, что контрольные и новые данные сохранились.

## Критерий успешного drill

- `pg_restore --list` и restore завершились с кодом 0;
- counts совпадают с manifest или заранее сохранёнными значениями;
- авторизация и контрольная доска работают;
- новая запись переживает повторный stop/start;
- safety backup сохранён отдельно и имеет проверенный SHA-256.

До выполнения этого сценария на копии production-подобных данных наличие
`pg_dump` считается механизмом backup, но не доказанным восстановлением.
