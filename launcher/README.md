# p2pKanban Launcher

Дата: 2026-10-22. Решение о направлении — [E-ADR-004](../docs/ecosystem/adr/E-ADR-004-ecosystem-launcher.md)
(принято John 2026-10-20).

Лаунчер экосистемы p2pKanban: одно окно, из которого видно, какие приложения
экосистемы есть, какие подходят этой машине, что установлено, что устарело
относительно `main`, и откуда их поставить, запустить и обновить.

## Новая машина: одной командой

Нужен только Python 3.11+ (git желателен, но не обязателен):

```bash
# Linux, macOS
curl -fsSL https://raw.githubusercontent.com/Pacifica123/p2pKanban-ecosystem/main/launcher/get.py | python3 -
# только лаунчер и web (sparse checkout), в свой каталог
curl -fsSL https://raw.githubusercontent.com/Pacifica123/p2pKanban-ecosystem/main/launcher/get.py | python3 - --only web --dir ~/p2p
```

```bat
:: Windows (cmd или PowerShell)
py -c "import urllib.request as u; exec(u.urlopen('https://raw.githubusercontent.com/Pacifica123/p2pKanban-ecosystem/main/launcher/get.py').read())"
```

[`get.py`](get.py) клонирует экосистему в `~/p2pkanban-ecosystem` (`--only` —
sparse по выбранным направлениям; без git или с `--archive` — zip последнего
коммита `main`), ставит окно (`install-gui`, `--no-gui` — пропустить) и пишет,
как запустить. Повторный запуск на том же каталоге его обновляет.

## Любая копия: zip от друга, «Download ZIP», копия UTS

git не обязателен ни для запуска, ни для сверки. Копия без git сверяется с
`main` по содержимому файлов: лаунчер считает sha каждого файла так же, как
git (`blob <размер>\0` + содержимое), и сравнивает с деревом каталога в `main`
на GitHub. Совпало — «актуально»; нет — лаунчер ищет совпадение среди 10
последних версий каталога в `main` и пишет «устарело: как main N коммитов
назад» или «не как в main» со списком отличающихся файлов. Лишние файлы копии
(кеши, сборки, `web/.dev-bootstrap`) не считаются, CRLF Windows — тоже.
Деревья по sha неизменны и кешируются: повторная проверка стоит один запрос.

Лаунчер, распакованный отдельно (рядом нет `ecosystem.json`), берёт каталог
направлений из `main` и показывает их «не скачано»; кнопка «Скачать с GitHub»
на карточке (`launcher.py get abl`) кладёт нужное направление в
`~/p2pkanban-ecosystem` — git-клоном, если git есть, иначе архивом `main`, — и
лаунчер дальше работает с этой копией. Каталог, которого нет в копии, той же
кнопкой докачивается: к sparse-клону — `sparse-checkout add`, к копии без
git — архивом `main` поверх.

## Запуск

Нужен Python 3.11–3.14. Один раз поставить окно (PySide6 в отдельный venv,
системный Python не трогается, около 70 МБ):

```bash
sh launcher/install.sh          # Linux, macOS
launcher\install.bat            # Windows (можно двойным щелчком)
```

Дальше из корня checkout экосистемы:

```bash
python launcher/launcher.py            # окно
python launcher/launcher.py status     # то же в терминале
python launcher/launcher.py status --json --offline
python launcher/launcher.py actions web                     # что web объявил лаунчеру
python launcher/launcher.py run web install --dry-run       # пробный прогон установки
python launcher/launcher.py run web install --set port=8091 # установить и запустить на порту 8091
python launcher/launcher.py settings web --set listen=lan   # запомнить настройку
python launcher/launcher.py run web --profile same-node-port --set port=8095
python launcher/launcher.py apk                             # ссылка на свежий APK и его свежесть
python launcher/launcher.py self-update --dry-run           # что придёт из main
python launcher/launcher.py self-update                     # обновить checkout (только чистый, fast-forward)
python launcher/launcher.py doctor                          # диагностика, отчёт JSON в кеше
```

На Windows вместо `python` можно `py`. `launcher.py` сам находит venv с
PySide6; если окна ещё нет, он говорит, какой скрипт запустить, и показывает
состояние в терминале. Повторный `install.sh` ничего не скачивает, если всё
уже стоит; `--force` пересоздаёт venv.

На Linux Qt нужны системные библиотеки графики. На Arch обычно всё есть; если
окно не открывается с ошибкой про платформу `xcb` —
`sudo pacman -S --needed libglvnd libxkbcommon fontconfig xcb-util-cursor`.

| Флаг | Что делает |
|---|---|
| `--offline` | не ходить в сеть, показать кеш `main` |
| `status --refresh` | спросить `main` заново, не дожидаясь кеша |
| `install-gui [--force]` | то, что делают `install.sh` и `install.bat` |
| `actions <направление> [--json]` | действия, настройки и варианты из `launcher.json` направления |
| `run <направление> [действие] [--set k=v] [--profile id] [--dry-run] [--yes]` | выполнить объявленное действие; без действия — `status` |
| `settings <направление> [--set k=v]` | показать или запомнить настройки (пустое значение — «решает направление») |
| `apk [--json]` | ссылка на последнюю APK из ленты, «ожидайте APK», «собирается» |
| `get [направления] [--dir] [--dry-run]` | скачать направления с GitHub в эту копию или, если её нет, в `~/p2pkanban-ecosystem` |
| `self-update [--dry-run]` | обновить копию, из которой запущен лаунчер: `git pull --ff-only` или (копия без git) архив `main` поверх |
| `self-status [--json]` | ответ `status` лаунчера о себе (лаунчер объявляет и себя в `launcher.json`) |
| `doctor [--json] [--offline]` | Python, окно, предпосылки всех направлений, их `status`, доступ к GitHub и ленте APK |

`GITHUB_TOKEN` в окружении необязателен: без него GitHub даёт 60 запросов в
час, а лаунчер делает семь не чаще раза в 10 минут (и разово — деревья
каталогов для копии без git, дальше они в кеше).

## Принцип

**Дирижёр, а не замена.** Лаунчер не владеет ни одним шагом развёртки: web
ставится своим `python bootstrap.py`, abl — своим pacman/AppImage-путём,
mobile — APK. Лаунчер выполняет только команды, которые направление само
объявило, и показывает только то, что направление само опубликовало.

- Только стандартная библиотека Python 3.11+.
- Всё, что видно в окне, доступно из CLI (`status --json`) для UTS и агента.
- «Актуально» в лаунчере не значит «принято»: приёмку даёт UTS на хосте.

## Состояние на 2026-10-22: ступени L2–L5 — web и abl из лаунчера, ссылка на APK, самообновление, любая копия

| Что | Откуда |
|---|---|
| Каталог: описание, платформы, шаги развёртки | `ecosystem.json` корня (`summary`, `platforms`, `requires`, `install`, `docs`) |
| Подходит ли машине | платформа хоста против `platforms`; abl вне Arch-based Linux — серый с причиной, Android — «на телефон» |
| Предпосылки | короткие пробы `requires`: Python, Docker (установлен, запущен, Linux containers, Compose v2), git, pacman, WebKitGTK |
| Глобальное состояние | GitHub: последний коммит `main` по каталогу каждого направления, `origin` доски; кеш 10 минут, без сети — кеш с пометкой |
| Состояние копии | git-checkout: git корня — последний локальный коммит каталога, незакоммиченные правки. Копия без git: sha файлов против деревьев `main` на GitHub (`launcher_app/source.py`) |
| Сверка исходников | актуально, устарело (на сколько коммитов каталога), впереди main, изменено локально / не как в main (какие файлы), не скачано, неизвестно |
| Действия и настройки | `<направление>/launcher.json` по контракту [`launcher-entry/1`](../contracts/launcher-entry/1/SPEC.md); объявили web и abl |
| APK Android | лента `apk.json` в ветке `launcher-feed`, её пишет GitHub Action с секретом `EXPO_TOKEN` ([feed/README.md](feed/README.md)) |
| Установлено | ответ `status` направления: не установлено, работает (с адресом), остановлено, установлено, не работает; рядом — актуальна ли установка относительно `main` (её коммит против последнего коммита каталога в `main`: git копии, иначе история каталога и GitHub compare). Если направление не сообщает коммит, берётся коммит копии, из которой лаунчер делал install/update |
| Темы | четыре темы словаря `p2p-kanban-ui-themes/1` (`launcher_app/themes.py`, из них же QSS окна); выбор и размер окна — в `settings.json` |

### Как лаунчер выполняет команды

- Только действия из `launcher.json` направления, и только его Python-скрипты:
  `argv[0]` — интерпретатор лаунчера, каталог — каталог направления, без
  оболочки. Значение настройки проверяется до запуска по объявлению.
- Перед запуском окно показывает команду целиком; если направление объявило
  пробный прогон (`--dry-run`), его можно выполнить первым.
- Действие с `confirm` (удалить узел, откат) не запускается без явного «да».
- Вывод идёт в окно построчно; «Прервать» останавливает процесс; у каждого
  действия свой предел времени из объявления.
- Что лаунчер запускал и с какими настройками — в `installs.json`; пробный
  прогон и `status` туда не пишутся.

### Web из окна

Карточка web показывает кнопки по состоянию узла: «Установить» → «Открыть» и
«Остановить» → «Запустить»; «Обновить», когда в `main` есть коммит `web/`
новее установленного. «Настройки» — порт (пусто — «авто») и доступ
(`--listen`), а также варианты: **тот же узел на другом порту** работает,
**второй, тестовый узел** показан серым с причиной — web пока держит один
узел на checkout (карточка на доске). В «Ещё» — откат, диагностика, логи,
удаление с базой. Без Docker кнопки неактивны и названо, чего не хватает.

### abl из окна (Arch-based Linux)

abl объявил `tools/user_install.py`: «Установить» собирает пакет pacman из
этого checkout (`makepkg`) и ставит его (`pacman -U`; пароль спросит `pkexec`),
«Обновить» пересобирает, только если checkout новее установленного, «Открыть»
запускает `p2pkanban`, в «Ещё» — удаление пакета (данные профиля остаются).
Первая сборка долгая: cargo и npm скачивают зависимости. Недостающие пакеты
сборки abl называет строкой `sudo pacman -S --needed …`. На Windows и macOS
карточка серая.

### Android

Карточка показывает последнюю готовую APK из ленты: «Скачать APK» открывает
ссылку, в «Ещё» — скопировать её (открыть на телефоне) и страница сборки. Рядом
вердикт: свежий APK, **ожидайте APK** (в `mobile/` есть коммит новее сборки),
**собирается**, ссылка истекла. Пока ленты нет (Action ещё не запускался или
не задан секрет), карточка ведёт на страницу сборок expo.dev и пишет, что
свежесть неизвестна. Что сделать один раз — [feed/README.md](feed/README.md).

### Сам лаунчер

Лаунчер объявляет и себя тем же контрактом ([`launcher.json`](launcher.json)):
его карточка в «Для разработки» показывает «Обновить», когда в `main` есть
коммит `launcher/` новее копии. Обновление git-checkout — только чистого и на
`main`, только fast-forward: свои правки и коммиты лаунчер не сливает и не
откатывает, а называет. Копия без git (архив, «Download ZIP», копия UTS)
обновляется архивом `main` поверх, по тем направлениям, что в ней есть: файлы перезаписываются, состояние направлений (например,
`web/.dev-bootstrap`) остаётся, удалённые в `main` файлы остаются у вас.
Установленный web этим не обновляется — у него своя кнопка «Обновить»; abl
после обновления checkout пересобирается своей.

«Диагностика» (`doctor`) ничего не меняет и сохраняет отчёт
`doctor-<время>.json` в кеше лаунчера; токены в нём только «задан / не задан».

L6 (вступление устройства в кольцо аккаунта при установке) ждёт решения John
по E-ADR-002. Ступени — [docs/ROADMAP.md](docs/ROADMAP.md).

## Где лаунчер хранит своё

| Что | Windows | Linux | macOS |
|---|---|---|---|
| `settings.json`, `installs.json`, `ecosystem-root.json` | `%APPDATA%\p2pkanban\launcher` | `$XDG_CONFIG_HOME/p2pkanban/launcher` | `~/Library/Application Support/p2pkanban/launcher` |
| кеш `main` | `%LOCALAPPDATA%\p2pkanban\launcher\cache` | `$XDG_CACHE_HOME/p2pkanban/launcher` | `~/Library/Caches/p2pkanban/launcher` |
| venv с PySide6 | `%LOCALAPPDATA%\p2pkanban\launcher\data\venv` | `$XDG_DATA_HOME/p2pkanban/launcher/venv` | `~/Library/Application Support/p2pkanban/launcher/data/venv` |

`P2PKANBAN_LAUNCHER_HOME` переносит всё это в один каталог (тесты, UTS). venv
намеренно не в checkout: его не захватят снимки devctl.

## Проверки

```bash
cd launcher
python -B -m unittest discover -s tests
```

Без сети и Docker. Своя реализация контракта сверяется с векторами
`contracts/launcher-entry/1/vectors/`. Проверка окна (offscreen) идёт, только если тесты запущены
интерпретатором venv с PySide6, иначе пропускается. Те же проверки — раздел
`launcher` в `tools/ecosystem/uts_plan.json`.

## Устройство

| Файл | Что делает |
|---|---|
| `launcher.py` | CLI, поиск venv и запуск окна |
| `get.py` | новая машина одной командой: клон, sparse или архив, затем `install-gui` (не импортирует `launcher_app`) |
| `launcher.json` | объявление лаунчера о себе: обновить checkout, диагностика, `self-status` |
| `install.sh`, `install.bat` | ищут Python 3.11–3.14 и вызывают `launcher.py install-gui` |
| `requirements-gui.txt` | зафиксированная версия PySide6 |
| `launcher_app/install.py` | venv и установка PySide6 |
| `launcher_app/probes.py` | платформа и предпосылки |
| `launcher_app/remote.py` | `main` на GitHub и кеш; `ecosystem.json` из `main` для лаунчера без экосистемы рядом |
| `launcher_app/source.py` | сверка копии без git: sha файлов против деревьев `main`, кеш деревьев по sha |
| `launcher_app/local.py` | checkout, реестр установок и сохранённые настройки направлений |
| `launcher_app/entry.py` | своя реализация `launcher-entry/1`: проверка `launcher.json`, argv, разбор `status` |
| `launcher_app/runner.py` | запуск объявленных команд, `status`, запись в реестр |
| `launcher_app/view.py` | какие кнопки показать на карточке (без Qt) |
| `launcher_app/qt_dialogs.py` | окна запуска действия и настроек направления |
| `launcher_app/apk.py` | лента APK: загрузка, кеш, вердикт для карточки Android |
| `feed/apk_feed.py` | сборка ленты из EAS; его запускает `.github/workflows/launcher-apk-feed.yml` |
| `launcher_app/selfupdate.py` | обновление копии: git fast-forward или архив `main` |
| `launcher_app/doctor.py` | диагностика и её отчёт |
| `launcher_app/state.py` | сборка состояния и сверка |
| `launcher_app/qt_app.py` | окно PySide6: только рисует состояние ядра |
| `launcher_app/themes.py` | копия словаря тем и QSS «пастельный пластик» |
| `launcher_app/settings.py` | тема и размер окна |

## Чем лаунчер не является

- не установщик Docker, JDK, Rust или WebKitGTK: он только проверяет, есть ли
  они, и говорит, что поставить;
- не замена devctl: патчи по-прежнему применяет devctl;
- не источник истины о направлениях: истина — их README и docs.
