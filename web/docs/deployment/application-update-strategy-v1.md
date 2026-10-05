# Обновление server-client без потери данных

- Статус: UI + CLI реализация beta.13
- Команда: `python bootstrap.py update`
- Только возобновить loopback UI-установщик: `python bootstrap.py watch-updates`
- Канал по умолчанию: GitHub-ветка `main`
- Область: zero-config Docker bootstrap

## Пользовательский путь

При локальном открытии через `127.0.0.1` или `localhost` web раз в десять минут
проверяет последний commit `main`. Плашка показывает первую строку commit
message и ссылку на GitHub. «До следующего commit» скрывает только этот SHA;
следующий push снова показывается.

После нажатия «Обновить» интерфейс показывает этапы и progress. Пока старый web
работает, progress остаётся в React overlay. Во время замены контейнера тот же
порт обслуживает maintenance page стабильного gateway. В конце появляется
кнопка «Перезапустить интерфейс».

CLI остаётся полноценным резервным путём:

Если release bundle содержит адрес исходного репозитория:

```bash
python bootstrap.py update
```

Если старый bundle ещё не содержал адрес, он задаётся один раз:

```bash
python bootstrap.py update \
  --repository https://github.com/owner/repository
```

Для локальной проверки новой копии исходников:

```bash
python bootstrap.py update --source-dir ../new-p2pkanban
```

Посмотреть план без Docker-переключения:

```bash
python bootstrap.py update --source-dir ../new-p2pkanban --dry-run
```

## Что updater меняет

Backend и frontend являются заменяемыми Docker images. PostgreSQL и секреты
хранятся в постоянных named volumes.

Updater:

1. получает exclusive lock;
2. проверяет работающий stack и свободное место;
3. получает SHA вершины `main` и скачивает архив именно этого immutable commit;
4. проверяет структуру, `VERSION`, Compose и встроенный bootstrap-check;
5. собирает versioned backend/web images, пока текущие контейнеры работают;
6. создаёт `pg_dump` вне Docker volumes;
7. помечает текущие images отдельным rollback-тегом;
8. сохраняет внешний порт за стабильным gateway и заменяет backend/web;
9. ждёт реальный upstream `/healthz`, не maintenance-ответ;
10. сравнивает counts основных данных, включая карточки, чек-листы, комментарии,
    оформление, tombstones и roaming events;
11. сохраняет несекретный JSON-отчёт и активный source/image tag.

Ни на одном шаге updater не выполняет `docker compose down --volumes`.

## Где остаются данные

| Данные | Место |
|---|---|
| PostgreSQL | прежний named volume |
| JWT secret и пароль БД | прежний закрытый volume |
| Backup перед update | `.dev-bootstrap/backups/update-*/p2pkanban.dump` |
| Полученные исходники | `.dev-bootstrap/releases/<update>/source` |
| Отчёт | `.dev-bootstrap/update-reports/<update>.json` |
| Несекретное состояние | `.dev-bootstrap/container-stack.json` |
| UI job и лог | `.dev-bootstrap/update-job.json`, `update-job.log` |
| Локальный control token | `.dev-bootstrap/update-control.json` (`0600` на Unix) |

Каталог `.dev-bootstrap` не входит в Git и Docker build context.

## Усыновление legacy deployment

Если Compose stack исторически запущен из временной post/UserTestSpace-копии,
beta.13 может перенести только управление в постоянный runtime root:

```bash
python bootstrap.py adopt-running
```

Команда сверяет Compose labels, опубликованный gateway-порт, одинаковый tag
backend/web, healthz и точные имена обоих named volumes. Затем она копирует
launcher/source без `.git`, `.env` и build-каталогов в
`<devctl-workspace>/runtime/p2pkanban-node`, переносит несекретное состояние и
перепривязывает updater. Контейнеры не перезапускаются, volumes не перемещаются
и не переименовываются. Source checkout остаётся Git-чистым; дальнейшие
bootstrap-команды делегируются зарегистрированному runtime root.

## Отказ до переключения

Если не скачался архив, не прошла проверка или не собрались images, работающие
контейнеры не трогаются. Backup БД создаётся после успешной сборки, но до
переключения.

## Автоматический откат

Если новые контейнеры не стали готовы либо контрольные counts уменьшились,
updater:

1. запускает сохранённые старые backend/web images;
2. использует тот же PostgreSQL volume;
3. сохраняет отчёт со статусом `rolled_back`;
4. не восстанавливает dump автоматически.

Автоматическое восстановление БД из dump не выполняется: это отдельная
разрушительная операция.

## Ручной rollback

После успешного update можно вернуть прошлый код:

```bash
python bootstrap.py rollback
```

Перед переключением создаётся ещё один `pg_dump`. БД остаётся текущей. Поэтому
миграции обновляемой линии должны следовать expand/contract:

1. добавить совместимые nullable/default поля;
2. выпустить код, понимающий старую и новую форму;
3. перенести данные;
4. удалять старую форму только в более позднем релизе.

## Почему не `git pull` внутри контейнера

Работающий контейнер не хранит Git credentials и не является редактируемым
сервером исходников. Новая версия строится рядом со старой и получает отдельный
image tag. Это позволяет проверить сборку до переключения и сохранить
предыдущий image для rollback.

## Почему кнопка не даёт Docker-права web-контейнеру

Docker socket не монтируется ни в backend, ни в web. `bootstrap.py start`
запускает отдельный stdlib control plane только на `127.0.0.1:8765`. Изменяющие
запросы требуют одновременно точный Origin текущего loopback web-порта и
случайный token из файла с локальными правами. LAN-клиент видит приложение, но
не получает updater surface: `127.0.0.1` на таком устройстве указывает уже не
на хост узла.

## Доверие к источнику

Сигнал новой версии — плавающая `main`, как задано проектом. После согласия
пользователя SHA фиксируется; если до скачивания вершина изменилась, операция
останавливается и просит принять новое предложение. HTTPS защищает передачу,
архив SHA и source fingerprint записываются в отчёт, но commit всё ещё не
равнозначен подписанному публичному релизу.

Для публичной стабильной версии следующий шаг — update manifest на GitHub
Release с точным commit, SHA-256 и immutable image digest. Текущая реализация
уже разделяет источник, сборку, активную версию и volumes, поэтому переход не
потребует менять модель хранения данных.

## Обязательный smoke на машине с Docker

1. Запустить предыдущую рабочую beta и создать аккаунт, пространство, доску и
   карточку.
2. Принять следующий commit через web и наблюдать overlay → maintenance →
   подтверждённую кнопку перезапуска на том же URL.
3. Проверить вход тем же аккаунтом, карточки, чек-листы и оформление.
4. Проверить `status`, job state и JSON-отчёт.
5. Остановить и снова запустить stack: порт не должен измениться.
6. Выполнить CLI `update --dry-run`, затем `rollback` и повторно проверить данные.
7. Убедиться, что `.dev-bootstrap/backups` содержит читаемые `pg_dump`.

Этот сценарий нужен на Windows с Docker Desktop и Linux с Docker Engine.
Отдельный destructive restore drill описан в
[`postgresql-backup-restore-v1.md`](postgresql-backup-restore-v1.md).
