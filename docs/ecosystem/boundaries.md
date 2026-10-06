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
| корень | `docs/ecosystem/`, `board/`, `ecosystem.json`, `tools/ecosystem/`, `.devctl/`, `AGENTS.md` | код и документация направлений |

Изменения внутри каталога направления подчиняются его собственным правилам
(его README, docs, проверкам). Корень их не переопределяет.

## Контракты между направлениями

Сегодня каждый контракт описан и проверяется внутри направлений отдельно. Это
нормально для старта: монорепозиторий впервые позволяет увидеть их рядом.

| Контракт | Кто производит | Кто потребляет | Где описан |
|---|---|---|---|
| HTTP API узла, включая `/api/v1/auth/native/*` | web | mobile | `web/docs/api/openapi.yaml` |
| Roaming доски `p2p-kanban-roaming/1` (Nostr, XChaCha20-Poly1305, порядок `logicalClock → replicaId → eventId`) | web, mobile | web, mobile, abl | `web/docs/sync/roaming-board-protocol-v1.md`, `abl/fixtures/protocol/` |
| Sync envelope `p2p-kanban-sync/1` | web `sync-core` | abl | `web/backend/crates/sync-core/src/envelope.rs`, `abl/docs/evidence/A10_SYNC_ROAMING_COMPATIBILITY.md` |
| Привязка устройства `p2p-kanban-device-link/2` | web | mobile, abl | `web/backend/src/auth/device_link.rs`, `abl/fixtures/protocol/device-link-grant-v2.json` |
| Перенос узла `p2p-kanban-web-node-link/1` | web | web, abl | `web/docs/architecture/web-node-link-v1.md` |
| Переносимая доска `p2p_planner_bundle` v1 | web, abl | web, abl, корневая доска | `web/docs/architecture/import-export-backup-v1.md`, `abl/src-tauri/src/domain/import.rs` |
| Patch manifest и `state.json` | devctl | все направления, `web/tools/devctl_receipt.py` | `devctl/docs/patch-format.md`, `devctl/docs/configuration.md` |
| devctl receipt и `.p2pkanban/project.json` | `web/tools/devctl_receipt.py` | web API интеграций | `web/docs/integrations/devctl-v2.md` |

### Предложенные контракты

Ещё не реализованы; описаны в [trusted-devices.md](trusted-devices.md):
`p2p-kanban-account-ring/1` (журнал кольца устройств аккаунта),
`p2p-kanban-keyring/1` (связка ключей аккаунта),
`p2p-kanban-rendezvous/1` (добавление устройства через relay по QR или коду).
Производят и потребляют web, mobile и abl.

### Правило порядка обновления

Когда патч меняет контракт, который производит web, сначала обновляются все
web-узлы, потом mobile и abl. Так уже сформулировано в PATCH_SUMMARY текущих
снапшотов, и это правило становится общим.

### Известный дрейф

`abl/evidence/source-anchors.json` фиксирует sha256 файлов web, Android и
devctl, на которых abl основал совместимость (снимок 2026-09-12). На момент
инициирующего патча изменилась половина якорей: 15 из 30 (web 4 из 15,
Android 9 из 12, devctl 2 из 3). Это не ошибка: якоря заморожены намеренно.
Но теперь дрейф можно измерять автоматически, потому что источники лежат в
одном дереве. Карточка об этом есть на доске.

## Что в инициирующем патче сознательно не связано

- Направления не импортируют код друг друга и не ссылаются на соседние
  каталоги.
- Установленные web-узлы продолжают обновляться из прежнего репозитория
  `Pacifica123/p2p_planner`: `web/tools/container_bootstrap.py` и
  `web/tools/update_control_plane.py` скачивают архив корня этого репозитория
  и ждут `bootstrap.py` в корне. В монорепозитории web лежит в `web/`, поэтому
  переключение канала обновления — отдельный будущий шаг.
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
