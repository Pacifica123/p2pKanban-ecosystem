# Zero-config bootstrap v1

## Цель

Обычный локальный запуск p2pKanban не должен требовать ручного создания
PostgreSQL-роли, базы, `.env`, согласования портов backend/frontend или
установки Rust и Node на хост.

Публичный пользовательский путь:

```bash
python bootstrap.py
```

Внешние зависимости — Python 3.11+ для wrapper и запущенный Docker с Compose v2
или новее (Linux containers). Компиляторы и PostgreSQL работают в контейнерах.

## Как устроен stack

```mermaid
flowchart TD
    Browser["Браузер"]
    Gateway["stable gateway"]
    Web["web: Nginx + frontend"]
    Backend["backend: Rust"]
    Postgres[("postgres")]
    Init["bootstrap-init"]
    Secrets[("закрытый volume секретов")]
    Data[("volume данных")]

    Browser -->|закреплённый порт| Gateway
    Gateway --> Web
    Web -->|/api| Backend
    Backend --> Postgres
    Init --> Secrets
    Secrets --> Backend
    Secrets --> Postgres
    Postgres --> Data
```

`postgres` и `backend` не публикуют порты на хост. Наружу выходит только
web-gateway. Поэтому установленный на компьютере PostgreSQL на `5432` не
мешает контейнерному PostgreSQL.

## Первый запуск

1. Wrapper проверяет наличие Docker CLI, Compose v2 и работающего Docker
   daemon.
2. Если `8080` свободен, выбирается он. Иначе выбирается первый свободный порт
   до `8180`; после первого запуска этот порт становится адресом узла.
3. `bootstrap-init` создаёт четыре секрета в Docker volume:
   пароль PostgreSQL, JWT secret, Nostr secret key и Nostr master key.
4. Официальный PostgreSQL image при первом старте создаёт:
   роль `p2pkanban`, БД `p2pkanban` и постоянный data volume.
5. Backend читает секреты из volume, собирает `DATABASE__URL` только внутри
   контейнера, подключается к БД и применяет миграции.
6. Frontend собирается с относительным API URL `/api/v1`.
7. Стабильный Nginx gateway публикует единственный порт, а versioned web отдаёт
   SPA; оба проксируют `/api` во внутренний backend.
8. Wrapper ждёт `/healthz`, сохраняет только несекретные сведения о stack в
   `.dev-bootstrap/container-stack.json` и открывает браузер.

Никакие `.env` не создаются. Секреты не попадают в Git, shell history, Compose
manifest или bootstrap state.

## Повторный запуск и остановка

```bash
python bootstrap.py
python bootstrap.py status
python bootstrap.py logs
python bootstrap.py logs --follow
python bootstrap.py stop
```

Повторный `start` использует прежний порт, БД и секреты. Если state-файл был
потерян, но Compose stack работает, bootstrap восстанавливает порт по Docker
labels. Если закреплённый порт занят чужим процессом, новый адрес не выбирается
молча: нужно освободить порт либо явно передать `--port`. `stop` удаляет
контейнеры и сеть, но сохраняет оба named volume.

Обновление кода выполняется отдельно:

```bash
python bootstrap.py update
```

После перезапуска компьютера Docker может поднять контейнеры раньше host
control plane. Web всё равно обнаруживает новый commit напрямую через read-only
GitHub API. Devctl будит установщик после push; вручную это можно сделать без
рестарта stack:

```bash
python bootstrap.py watch-updates
```

Legacy stack, запущенный из временной post/UserTestSpace-копии, сначала
привязывается к постоянному runtime root без рестарта контейнеров:

```bash
python bootstrap.py adopt-running
```

Команда проверяет работающие images, gateway `healthz` и оба named volume,
создаёт `<devctl-workspace>/runtime/p2pkanban-node` и регистрирует его вне Git
checkout. После этого `status`, `update`, `rollback`, `stop` и
`watch-updates`, вызванные из source checkout, делегируются runtime root.

Bootstrap собирает новые backend/web images рядом с работающими, создаёт
`pg_dump`, переключает их на прежние volumes и автоматически возвращает старые
images при ошибке readiness. Подробности:
[`application-update-strategy-v1.md`](application-update-strategy-v1.md).

При loopback-доступе ту же операцию можно принять из web-плашки нового commit.
Host control plane слушает только `127.0.0.1:8765`; Docker socket в контейнеры
не передаётся. Во время короткой замены web стабильный gateway отдаёт
maintenance page на прежнем URL.

Предыдущий код можно вернуть без автоматического восстановления БД:

```bash
python bootstrap.py rollback
```

Полный сброс намеренно требует явного подтверждения:

```bash
python bootstrap.py reset --yes
```

Он удаляет локальную БД и секреты. Следующий запуск создаст чистую установку.

## Режим локальной сети

По умолчанию web-порт привязан к `127.0.0.1` и доступен только на текущем
компьютере.

Для доверенной локальной сети:

```bash
python bootstrap.py start --listen lan
```

Это обычный HTTP без публичного TLS. Его нельзя пробрасывать напрямую в
интернет. Для доступа через интернет применяется отдельный
`deploy/home-coordinator` с Tailscale либо будущий transport stack.

## Запуск без Python-wrapper

Compose stack сам создаёт секреты и БД, поэтому его можно поднять напрямую:

```bash
docker compose \
  --project-name p2pkanban-bootstrap \
  --file deploy/bootstrap/compose.yaml \
  up --detach --build
```

В таком режиме используется фиксированный `127.0.0.1:8080`, не выполняется
автопоиск свободного порта и браузер не открывается.

## Границы

- Это локальный/self-host bootstrap, а не coordinator-free P2P-режим.
- Nostr включён для roaming; bootstrap создаёт ключи в persistent secret volume.
  Iroh остаётся отключённым экспериментальным транспортом.
- Внешний PostgreSQL не подхватывается и не изменяется.
- Существующий host-native `tools/devbootstrap.py up` остаётся разработческим
  путём для release gates и точечной диагностики.
- Docker volumes являются локальным состоянием. Для важных досок всё ещё нужен
  экспорт/backup.

## Диагностика

| Симптом | Что делает bootstrap |
|---|---|
| Docker CLI отсутствует | Останавливается с одной инструкцией установить Docker |
| Docker Desktop закрыт | Останавливается до сборки и просит запустить daemon |
| `8080` занят при первом запуске | Выбирает следующий свободный порт и закрепляет его |
| Закреплённый порт занят после остановки | Не смещает узел; просит освободить порт или явно выбрать новый |
| State потерян, stack работает | Находит принадлежащий узлу порт по Compose labels |
| PostgreSQL уже работает на хосте | Игнорирует его; `5432` контейнера наружу не публикуется |
| Первый build упал | Показывает `compose ps` и последние логи |
| Повторный запуск | Сохраняет прежнюю БД, секреты и web-порт |
| Обновление не собралось | Оставляет работающие контейнеры без изменений |
| Новая версия не прошла readiness | Возвращает сохранённые старые images |
| Web переключается | Gateway показывает progress/maintenance на прежнем URL |
| Нужна предыдущая версия кода | `rollback` создаёт backup и переключает images без удаления volumes |
| Нужна чистая установка | Только явный `reset --yes` удаляет volumes |

Первый build также сохраняется в `.dev-bootstrap/container-runs/*_start.log`,
включая ошибки `npm ci`, когда контейнеров приложения ещё нет.
`python bootstrap.py doctor` создаёт JSON-отчёт Docker/Compose/buildx,
контейнерных логов и контрольных сумм миграций. Код возврата `1` означает,
что приложение пока не прошло health-check; сам отчёт при этом сохраняется.
Подробнее: [переносимый запуск](portable-startup-v1.md).
