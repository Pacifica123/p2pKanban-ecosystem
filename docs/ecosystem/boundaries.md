# Границы и контракты

## Решение

Каждое направление владеет своим каталогом целиком. Корневой слой владеет
только связями: метадокументацией, доской, картой направлений и корневыми
проверками. Связь между направлениями существует лишь там, где есть явный
версионированный контракт.

## Кто чем владеет

| Владелец | Что входит | Что не входит |
|---|---|---|
| `web/` | Docker-стек, backend API, sync-core, миграции PostgreSQL, web UI, bootstrap и обновление узла | правила для mobile и abl |
| `mobile/` | Expo-клиент, local-first хранилище, Nostr roaming на Android, сборка APK | backend и миграции |
| `abl/` | Tauri-оболочка, Rust core, SQLite-профиль, pacman/AppImage-упаковка, UTS-проверки | Docker и localhost-backend |
| `devctl/` | формат патча, конвейер `start`, приём патчей, эволюционный архив | смысл патчей конкретного продукта |
| `launcher/` | окно лаунчера, его CLI, реестр установок на машине пользователя, сверка с `main` ([E-ADR-004](adr/E-ADR-004-ecosystem-launcher.md)) | шаги развёртки направлений: лаунчер только вызывает объявленные ими команды |
| корень | `docs/ecosystem/`, `contracts/`, `board/`, `ecosystem.json`, `tools/ecosystem/`, `.devctl/`, `AGENTS.md` | код и документация направлений |

Изменения внутри каталога направления подчиняются его собственным правилам
(его README, docs, проверкам). Корень их не переопределяет.

## Контракты между направлениями

Сегодня каждый контракт описан и проверяется внутри направлений отдельно. Это
нормально для старта: монорепозиторий впервые позволяет увидеть их рядом.

| Контракт | Кто производит | Кто потребляет | Где описан |
|---|---|---|---|
| HTTP API узла, включая `/api/v1/auth/native/*` | web | web UI, mobile, abl (frontend через desktop-транспорт) | `web/docs/api/openapi.yaml`; отстаёт от узла, перенос в `contracts/` принят в [E-ADR-001](adr/E-ADR-001-shared-documentation-layer.md) |
| Roaming доски `p2p-kanban-roaming/1` (Nostr, XChaCha20-Poly1305, порядок `logicalClock → replicaId → eventId`) | web, mobile | web, mobile, abl | `web/docs/sync/roaming-board-protocol-v1.md`, `abl/fixtures/protocol/` |
| Sync envelope `p2p-kanban-sync/1` | web `sync-core` | abl | `web/backend/crates/sync-core/src/envelope.rs`, `abl/docs/evidence/A10_SYNC_ROAMING_COMPATIBILITY.md` |
| Привязка устройства `p2p-kanban-device-link/2` | web | mobile, abl | `web/backend/src/auth/device_link.rs`, `abl/fixtures/protocol/device-link-grant-v2.json` |
| Перенос узла `p2p-kanban-web-node-link/1` | web | web, abl | `web/docs/architecture/web-node-link-v1.md` |
| Переносимая доска `p2p_planner_bundle` v1 | web, abl | web, abl, корневая доска, `project-board/1` | `web/docs/architecture/import-export-backup-v1.md`, `abl/src-tauri/src/domain/import.rs` |
| Отчёт кнопки приёмки `p2p-kanban-acceptance-report/1` | web UI, mobile (позже abl) | человек и агент, разбирающие приёмку; позже UTS | `docs/ecosystem/self-acceptance.md` |
| Patch manifest и `state.json` | devctl | все направления, `web/tools/devctl_receipt.py` | `devctl/docs/patch-format.md`, `devctl/docs/configuration.md` |
| Каталог приложений: `ecosystem.json` (`summary`, `platforms`, `requires`, `install`, `distribution`) | корень | launcher (L1) | [E-ADR-004](adr/E-ADR-004-ecosystem-launcher.md) п.3 |
| Объявление направления для лаунчера `p2p-kanban-launcher-entry/1` (`<направление>/launcher.json`: команды и настройки) | web, abl (с L2, L3) | launcher | **будущий**, [E-ADR-004](adr/E-ADR-004-ecosystem-launcher.md) п.3; появится в `contracts/` патчем L2 |
| Сборки APK в EAS (expo.dev): проект `ecosystem.json#mobile.eas`, профиль `preview` | mobile (`eas build`) | launcher (с L4, по токену Expo) | **будущий**, [E-ADR-004](adr/E-ADR-004-ecosystem-launcher.md) п.6 |
| devctl receipt и `.p2pkanban/project.json` | `web/tools/devctl_receipt.py` | web API интеграций | `web/docs/integrations/devctl-v2.md` |
| Номер патча сборки: `origin.boardRevision` и `origin.lastPatchId` доски, `BUILD_PATCH.json`, `P2PKANBAN_PATCH_*` | корень (каждый патч обновляет доску), updater web (`BUILD_PATCH.json`) | сборки web, mobile, abl: строка «патч N · patchId» рядом с версией | `board/README.md`, «Номер патча в версии клиентов» |

### Контракты в `contracts/`

Лежат в [`contracts/`](../../contracts/README.md): спецификация, JSON Schema и
эталонные векторы; кто их уже реализовал — в `compatibility.json`, проверка `python -B tools/ecosystem/check_contracts.py`.
Зачем они нужны, рассказывает [trusted-devices.md](trusted-devices.md).

| Контракт | Кто производит | Кто потребляет | Где описан |
|---|---|---|---|
| Журнал кольца устройств `p2p-kanban-account-ring/1` | web, mobile, abl | web, mobile, abl | `contracts/account-ring/1/` |
| Связка ключей `p2p-kanban-keyring/1` | web, mobile, abl | web, mobile, abl | `contracts/keyring/1/` |
| Встреча по QR `p2p-kanban-rendezvous/1` | web, mobile, abl | web, mobile, abl | `contracts/rendezvous/1/` |
| Подробности ошибки `p2p-kanban-error-report/1` | web UI, mobile, abl (отчёт); web-узел (`errorId`, заголовок версии) | человек и нейросеть, разбирающие ошибку | `contracts/error-report/1/` |
| Доска проекта `p2p-kanban-project-board/1` | корень (`board/board.json`), web-узел (`GET /api/v1/project-board`) | web UI, mobile, abl — только чтение, вне синхронизации | `contracts/project-board/1/`, [E-ADR-003](adr/E-ADR-003-project-board-in-clients.md) |

Кто какой контракт уже реализует и с какой версии, записано в
[`contracts/compatibility.json`](../../contracts/compatibility.json). Порядок
реализации: web (R2) → mobile (R3) → abl (R6).

### Правило порядка обновления

Когда патч меняет контракт, который производит web, сначала обновляются все
web-узлы, потом mobile и abl. Так уже сформулировано в PATCH_SUMMARY текущих
снапшотов, и это правило становится общим.

### Известный дрейф

`abl/evidence/source-anchors.json` фиксирует sha256 файлов web, Android и
devctl, на которых abl основал совместимость (снимок 2026-09-12). Это не
ошибка: якоря заморожены намеренно, и корень их не правит.

Дрейф измеряет корневая проверка:

```bash
python -B tools/ecosystem/anchor_drift.py          # какие якоря разошлись
python -B tools/ecosystem/anchor_drift.py --json   # то же для машин
```

Источник `android` в якорях — каталог `mobile/`. Код возврата 0 при любом
дрейфе; ненулевой — только если файл якорей нечитаем. Рядом с якорем
выводятся проверки abl (`abl/tools/check_a*.py`), которые упоминают этот путь:
по ним видно, совместимость какого этапа задета. Проверка входит в шаблон
манифеста, поэтому отчёт лежит в логе каждого `devctl start`.

На инициирующем патче разошлись 15 из 30 якорей, на 66d4ca6 (2026-10-20) —
16 из 30: web 5 из 15, mobile 9 из 12, devctl 2 из 3. Переснять якорь может
только патч abl, перепроверив совместимость с изменённым файлом соседа.

## Что в инициирующем патче сознательно не связано

- Направления не импортируют код друг друга и не ссылаются на соседние
  каталоги.
- Канал обновления web-узлов — ветка `main` монорепозитория
  `Pacifica123/p2pKanban-ecosystem` (с патча 2026-10-16-web-update-channel-monorepo).
  Обновлением считается последний коммит `main`, менявший `web/`; коммиты в
  mobile, abl, devctl или доску плашку обновления не показывают. Из архива
  коммита `web/tools/update_control_plane.py` и `web/tools/container_bootstrap.py`
  берут только `web/`. Сохранённый в узле адрес `Pacifica123/p2p_planner`
  переводится на монорепозиторий; узлу со старым updater нужен один ручной
  переход (`python bootstrap.py update --source-dir <checkout>/web`).
- Работающий узел остаётся в своём прежнем каталоге. Перенос состояния узла
  в checkout монорепозитория не выполняется.
- У devctl остаётся собственный `devctl/.devctl/workspace.json` (с устаревшим
  разделом `stage0`). devctl ищет workspace вверх от текущего каталога, поэтому
  команды devctl для экосистемы запускаются **из корня** репозитория.
- В `web/tools/devctl.py` лежит старая копия devctl v0.2. Каноническая версия —
  `devctl/devctl.py`.

## Признаки нарушения границы

- файл направления ссылается на `../web`, `../mobile`, `../abl` или `../devctl`;
- корневая проверка требует инструмент, которого нет в README направления;
- изменение контракта приходит в одно направление без карточки для остальных;
- метадокумент пересказывает внутреннее устройство направления.
