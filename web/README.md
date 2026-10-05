# p2pKanban

Изменения v2.0.0 и границы автономной синхронизации: [описание релиза](docs/product/v2.0.0-release-notes.md).

p2pKanban — экспериментальный local-first планировщик с досками, колонками и карточками.
Проект можно держать у себя, менять клиент и постепенно переходить на P2P/relay транспорты.

Текущая версия — `v2` (`2.0.0`): разработка непрерывна без каналов stable/dev/beta, а следующий `vN` обозначает новую сессию развития.

## Быстрый запуск

Нужны Python 3.11+ и запущенный Docker Desktop в режиме Linux containers либо
Docker Engine с Compose v2 или новее. Rust, Node и PostgreSQL на хосте не нужны.

Из корня проекта:

```bash
python bootstrap.py
```

На Windows вместо `python` можно использовать `py bootstrap.py`.

Bootstrap сам:

- при первом запуске найдёт свободный web-порт и закрепит его за узлом;
- создаст контейнеры, сгенерирует и сохранит случайные секреты;
- создаст PostgreSQL-роль и БД;
- соберёт backend и frontend;
- применит миграции;
- дождётся готовности приложения;
- откроет его в браузере.

Создавать `.env` и вручную выполнять SQL не нужно. Первый build может занять несколько минут.

[Сетевые сбои, безопасная замена старой версии и офлайн-установка](docs/deployment/resilient-bootstrap-v2.md).

## Обычные команды

| Действие | Команда |
|---|---|
| Запустить stack | `python bootstrap.py` |
| Обновить из `main` | плашка в web либо `python bootstrap.py update` |
| Запустить UI-установщик без рестарта stack | `python bootstrap.py watch-updates` |
| Вернуть прошлую версию кода | `python bootstrap.py rollback` |
| Посмотреть состояние | `python bootstrap.py status` |
| Сохранить диагностику запуска и миграций | `python bootstrap.py doctor` |
| Посмотреть последние логи | `python bootstrap.py logs` |
| Следить за логами | `python bootstrap.py logs --follow` |
| Остановить, сохранив данные | `python bootstrap.py stop` |

После `stop` БД остаётся в Docker volume и вернётся при следующем запуске.

Полный сброс удаляет локальные данные и потому требует явного подтверждения:

```bash
python bootstrap.py reset --yes
```
Если Docker установлен, но закрыт, bootstrap остановится сразу и попросит
запустить Docker Desktop. Он не будет пытаться использовать или перенастраивать
случайный PostgreSQL с компьютера.

Подробности: [`docs/deployment/zero-config-bootstrap-v1.md`](docs/deployment/zero-config-bootstrap-v1.md).
Перенос Windows/Linux: [`portable-startup-v1.md`](docs/deployment/portable-startup-v1.md).
Web на loopback сам проверяет новый commit в `main` и показывает его сообщение;
read-only проверка работает после перезапуска компьютера, а devctl после push автоматически будит локальный установщик.
Принятое обновление собирает images отдельно, создаёт PostgreSQL backup, затем
переключает backend/web за стабильным gateway на прежние volumes. CLI
`python bootstrap.py update` остаётся равноправным аварийным путём.

## Что уже работает

- регистрация, вход и refresh-сессия;
- workspaces, boards, columns и cards;
- перемещение карточек;
- описание, приоритет и положение карточки в пользовательской колонке;
- labels, checklists и comments;
- прогресс чек-листов прямо на карточках доски;
- 84-дневная сетка продуктивности по реальным действиям;
- история активности и audit API;
- читаемая русская история без ложных перемещений от checklist-синхронизации;
- настройки внешнего вида пользователя и доски, включая wallpaper по URL;
- локальные напоминания карточек в web и системные напоминания на Android;
- UI-обновление Docker-связки с commit message, progress, backup и rollback;
- локальный snapshot и очередь pending operations;
- backend-координируемая push/pull синхронизация;
- экспорт доски/workspace и импорт board-level JSON как новой копии;
- независимый `sync-core`;
- Nostr shadow outbox/recovery и native Iroh adapter как экспериментальный transport foundation;
- отдельный Android-клиент с native auth, локальными snapshot и независимой
  Nostr-синхронизацией карточек и чек-листов;
- изменения Android появляются на открытой web-доске после короткого polling;
- checklist roaming использует entity-delta и не удаляет пункты поздним snapshot;
- явное связывание чистого второго web-узла с основным узлом в доверенной LAN:
  переносятся identity, owned workspaces, доски и ключи roaming.

## Что пока не готово

- coordinator-free P2P как основной режим;
- полное равенство функций web и Android;
- merge и destructive restore/import поверх существующих данных;
- законченный conflict-resolution UI;
- production-ready integrations/webhooks.

Не считайте наличие будущего контракта в коде готовой пользовательской
функцией. Актуальная карта состояния:
[`docs/product/v1-execution-roadmap.md`](docs/product/v1-execution-roadmap.md).

### Перенос доски через JSON

На открытой доске кнопка сохранения скачивает board-level backup JSON. Чтобы
восстановить его, откройте список досок нужного workspace, выберите
`Импорт доски из JSON`, проверьте состав и нажмите `Создать копию`.

Импорт не перезаписывает существующую доску и не переносит сессии, старые ID,
авторов или старую activity history. Подробности:
[`docs/architecture/import-export-backup-v1.md`](docs/architecture/import-export-backup-v1.md).

### Второй независимый web-узел

Email уникален только внутри одного deployment. На чистом втором узле v1
выберите `Подключить с другого узла`; ненужную локальную копию после проверки
можно удалить командой `python bootstrap.py reset --yes`. Полный порядок:
[`docs/architecture/web-node-link-v1.md`](docs/architecture/web-node-link-v1.md).

Удаление карточки: локальное скрытие или глобальный tombstone — [`docs/sync/card-deletion-scopes-v1.md`](docs/sync/card-deletion-scopes-v1.md).

## Как это устроено

```text
browser
   |
web gateway (Nginx + React/Vite)
   |
Rust/Axum backend
   |
PostgreSQL
```

В обычном bootstrap-режиме наружу опубликован только web-gateway. PostgreSQL и
backend остаются во внутренней Docker-сети, поэтому порт `5432` на компьютере
не занимается.

Данные доски при работе приложения также сохраняются локально в клиенте.
Сетевой координатор пока принимает общий порядок изменений и проверяет права.
Nostr, Iroh и Durable Object являются дополнительным направлением развития, а
не скрытой заменой текущего backend.

## Доступ из локальной сети

По умолчанию приложение доступно только на текущем компьютере.

Для доверенной локальной сети:

```bash
python bootstrap.py start --listen lan
```

Это обычный HTTP-режим. Не публикуйте его порт напрямую в интернет. Для
удалённого приватного доступа используйте профиль
[`deploy/home-coordinator`](deploy/home-coordinator/README.md) с Tailscale.

## Разработка без контейнеров

Для работы над исходниками остаётся старый host-native путь:

```bash
python tools/devbootstrap.py self-check --no-write-report
python tools/devbootstrap.py diagnose --no-write-report
python tools/devbootstrap.py up --dry-run
```

Он предназначен для разработчиков, release gates и подробной диагностики. В
этом режиме нужны локальные Rust, Node и PostgreSQL либо отдельный dev-compose.

Backend запускается однозначно:

```bash
cd backend
cargo run --bin p2p-planner-backend
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

## Документация

- [`docs/README.md`](docs/README.md) — карта документации;
- [`docs/product/v1-execution-roadmap.md`](docs/product/v1-execution-roadmap.md) — что реально готово;
- [`docs/architecture/project-structure.md`](docs/architecture/project-structure.md) — структура проекта;
- [`docs/api/openapi.yaml`](docs/api/openapi.yaml) — HTTP API;
- [`docs/deployment/zero-config-bootstrap-v1.md`](docs/deployment/zero-config-bootstrap-v1.md) — новый bootstrap;
- [`docs/deployment/application-update-strategy-v1.md`](docs/deployment/application-update-strategy-v1.md) — обновление и rollback;
- [`docs/deployment/postgresql-backup-restore-v1.md`](docs/deployment/postgresql-backup-restore-v1.md) — PostgreSQL backup/restore;
- [`docs/architecture/client-uiux-flat-pass-v1.md`](docs/architecture/client-uiux-flat-pass-v1.md) — разбор UI/UX-карты и flat-проход;
- [`docs/architecture/web-node-link-v1.md`](docs/architecture/web-node-link-v1.md) — перенос identity и досок между двумя web-узлами;
- [`docs/deployment/free-hosting-transports-v1.md`](docs/deployment/free-hosting-transports-v1.md) — бесплатные transport-варианты;
- [`docs/adr/ADR-006-homeless-board-transport-stack.md`](docs/adr/ADR-006-homeless-board-transport-stack.md) — выбранная transport-архитектура;
- [`docs/dev-bootstrap/devbootstrap-v1-operations.md`](docs/dev-bootstrap/devbootstrap-v1-operations.md) — расширенная локальная диагностика;
- [`docs/product/version-policy.md`](docs/product/version-policy.md) — политика непрерывных версий `vN`;
- [`docs/product/github-devctl-project-integration-concept-v1.md`](docs/product/github-devctl-project-integration-concept-v1.md) — концепция GitHub/devctl.

## Проверки

Минимальная проверка нового bootstrap:

```bash
python -B tools/check_zero_config_bootstrap.py
```

Полный набор локальных release gates:

```bash
python -B tools/devbootstrap.py release-gates --profile full-local-release
```

## v2.1.0 — локальное подтверждение узлов

Доверенные узлы подключаются по IP:порту в настройках сети, получают права на доски и публикуют каталог через relay. См. [описание ограничений](docs/architecture/device-network-v2.1.0.md).


Разные сети и исправление E0599 при обновлении: [инструкция и проверка](docs/architecture/network-recovery-20261001.md).

## 2026-10-01 correction

See [Shared history and cross-network recovery](docs/architecture/shared-history-and-node-connectivity.md).
