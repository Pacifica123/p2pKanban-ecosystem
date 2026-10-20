# p2pKanban — экосистема

Один репозиторий, пять самостоятельных направлений. Снаружи это одно место,
где живёт весь канбан; внутри каждое направление остаётся собой: со своим
стеком, своими командами, своей документацией и своей философией.

| Каталог | Направление | Что это | Как запустить |
|---|---|---|---|
| [`web/`](web/README.md) | web | Self-hosted узел: React/Vite + Rust/Axum + PostgreSQL в Docker | `cd web && python bootstrap.py` |
| [`mobile/`](mobile/README.md) | Android | React Native/Expo-клиент, local-first + Nostr roaming | `cd mobile && npm ci && npm run apk` |
| [`abl/`](abl/README.md) | Arch-based Linux | Нативный Tauri 2 + Rust + SQLite клиент без Docker | `cd abl && python3 -B tools/uts_verify.py` |
| [`devctl/`](devctl/README.md) | devctl | Конвейер zip-патчей для всех направлений | `python3 devctl/devctl.py self install` |
| [`launcher/`](launcher/README.md) | launcher | Лаунчер экосистемы: витрина приложений, установка, обновление и сверка с `main` своими командами направлений ([E-ADR-004](docs/ecosystem/adr/E-ADR-004-ecosystem-launcher.md), ступень L0) | `sh launcher/install.sh` (Windows: `launcher\install.bat`), затем `python launcher/launcher.py` (с L1) |

Каждая команда выполняется **из каталога своего направления**, ровно как раньше
из корня отдельного репозитория. Монорепозиторий ничего не меняет для конечного
пользователя: это общее место хранения, а не новый продукт.

## Взять только одно направление

Скачивать всё не обязательно. Например, только Linux-клиент:

```bash
git clone --filter=blob:none --sparse https://github.com/<owner>/<repo>.git p2pkanban
cd p2pkanban
git sparse-checkout set abl
cd abl
```

Так же работает `web`, `mobile` или любой их набор (`git sparse-checkout set web mobile`).
Удобную выборочную и настраиваемую установку берёт на себя [лаунчер](launcher/README.md)
(отдельное направление, [E-ADR-004](docs/ecosystem/adr/E-ADR-004-ecosystem-launcher.md));
его ступени — на [доске](board/board.json) с меткой `launcher`.

## Что лежит в корне

| Путь | Назначение |
|---|---|
| [`docs/ecosystem/`](docs/ecosystem/README.md) | Метадокументация: принципы координации, границы, devctl, разработка, путь интеграции, критерии успеха |
| [`board/board.json`](board/README.md) | Самоприменимая доска экосистемы: импортируется в сам p2pKanban и обновляется каждым патчем |
| [`ecosystem.json`](ecosystem.json) | Машиночитаемая карта направлений |
| [`tools/ecosystem/`](tools/ecosystem/check_board.py) | Проверка доски и карты направлений; [общий тестер приёмки UTS](docs/ecosystem/uts.md) |
| [`AGENTS.md`](AGENTS.md) | Короткие правила для нейросети, готовящей патч |
| `.devctl/workspace.json` | Корень как devctl-workspace: один поток патчей на всю экосистему |

## Главное правило разработки

Каждый патч обновляет `board/board.json`. Без этого патч не считается готовым:
проверка `python -B tools/ecosystem/check_board.py --require-changed` его
остановит. Подробности — [docs/ecosystem/development.md](docs/ecosystem/development.md).

## Приёмка на хосте

Исходники в репозитории — ещё не принятое. Приёмку на машине владельца
проводит одна команда из корня (или из копии в `UserTestSpace`):

```bash
python3 -B tools/ecosystem/uts.py
```

Она проверяет все направления, даёт каждому PASS или FAIL, считает общую
готовность и показывает, если на хосте или телефоне стоит не та версия.
Логи — в `.uts/` папкой и таким же zip. Подробности —
[docs/ecosystem/uts.md](docs/ecosystem/uts.md).
