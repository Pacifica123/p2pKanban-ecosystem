# Devctl v0 — уточнения перед реализацией

Этот документ фиксирует свежий обзор стратегии `devctl` перед непосредственной реализацией тулзы. Смысл документа — не заменить уже написанную спецификацию, а добавить к ней несколько практических guardrails, которые стоит учесть в коде v0.

## 1. `requiredCommands` лучше проверять до применения патча

В текущем конвейере важно не менять рабочее дерево, если заранее понятно, что checks всё равно не смогут выполниться.

Рекомендуемый порядок для `start`:

1. discover workspace/project;
2. load state registry;
3. find patch candidate;
4. read and validate `manifest.json`;
5. validate Git clean/sync state;
6. validate `checks[].requiredCommands` through `shutil.which`;
7. validate `checks[].cwd` exists;
8. only then create pre-archive and apply patch.

Почему это важно:

- если на машине нет `cargo`, `npm`, `python` или другой required command, патч не должен успеть сделать рабочее дерево dirty;
- missing tool — это environment/preflight failure, а не failed patch application;
- так проще объяснять пользователю, что исправить: сначала поставить инструмент, потом снова запустить `devctl start`.

Комментарий к реализации:

- `requiredCommands` проверять для всех checks до apply;
- если команда не найдена — писать report/status как preflight failure или invalid environment;
- в v0 можно не создавать большой pre/post archive при preflight failure, но полезно создать короткий diagnostic report в `.devctl` или в минимальном archive-run directory;
- команды искать через `shutil.which`, учитывая Windows-варианты вроде `npm.cmd`, `cargo.exe`, но обычно `which("npm")` на Windows сам умеет найти `.cmd` через `PATHEXT`.

## 2. State registry не должен быть единственным источником правды

`.devctl/state.json` полезен для локальной истории прогонов, но он не решает проблему нескольких машин полностью. На другой машине этого файла может не быть, либо он может быть устаревшим.

Поэтому успешный commit должен содержать технические trailers в теле commit message:

```text
Patch-Id: 2026-04-30-release-workflow-automation
Patch-SHA256: 7f3a9c...
Devctl-Version: 0
```

Почему это важно:

- GitHub становится реальным source of truth;
- другая машина может понять, что patch уже применен, даже без локального `.devctl/state.json`;
- проще диагностировать историю: какой patch породил какой commit;
- меньше риска повторно применить один и тот же patch после pull на другой машине.

Комментарий к реализации:

- при успешном commit формировать message из `manifest.commit.message` + пустая строка + trailers;
- `status` может в v0 только показывать локальный state registry, но желательно сразу заложить функцию чтения последних commit messages;
- `start` должен сначала проверять `state.json`, а затем, если patch не найден там, опционально искать `Patch-SHA256` или `Patch-Id` в последних N коммитах;
- для v0 достаточно проверить последние 50-100 коммитов текущей ветки.

## 3. Latest patch по `mtime` — fallback, а не основной порядок

Выбирать newest patch только по file modification time хрупко, потому что при копировании между машинами timestamp может измениться.

Рекомендуемый порядок сортировки patch candidates:

1. `manifest.createdAt`, если manifest читается;
2. timestamp из имени `patch_YYYYMMDD_HHMMSS_slug.zip`;
3. fallback на file `mtime`.

Почему это важно:

- меньше путаницы при переносе патчей через архивы/мессенджеры/облако;
- порядок применения ближе к тому, как патчи реально создавались;
- `mtime` остается полезным только как запасной вариант.

Комментарий к реализации:

- сначала собрать список `patches/*.zip`;
- для каждого zip попробовать быстро прочитать `manifest.json`;
- если manifest битый — не применять, но показать как invalid candidate;
- если `createdAt` есть, парсить ISO datetime best-effort;
- если `createdAt` нет, парсить имя через regex `patch_(\d{8})_(\d{6})_`;
- если ничего не получилось, использовать `stat().st_mtime`.

## 4. Нужен не auto-rollback, а понятная recovery-инструкция

Автоматический rollback в v0 лучше не делать. Он может оказаться опаснее, чем грязное дерево после failed patch, особенно если ошибка произошла посередине apply/checks.

Вместо этого каждый failed/interrupted report должен содержать recovery-блок.

Пример:

```bash
git status
git diff
# Осторожно: следующие команды откатывают локальные изменения.
git reset --hard HEAD
# Осторожно: удаляет untracked files/directories.
git clean -fd
```

Почему это важно:

- пользователь видит, что именно произошло;
- есть архив failed-state для анализа;
- нет скрытой магии, которая может удалить что-то неожиданно;
- recovery остается осознанным ручным действием.

Комментарий к реализации:

- при failed checks создать failed archive;
- не commit, не push;
- оставить рабочее дерево как есть;
- в report явно написать: “working tree was left dirty for inspection”;
- если ошибка случилась до apply, писать, что рабочее дерево не менялось;
- если ошибка случилась после apply, писать путь к failed archive и команды ручного отката.

## 5. Windows path safety надо сделать параноидальнее

Safe apply уже должен запрещать absolute paths и `..`, но на Windows есть дополнительные формы опасных путей.

Нужно явно отклонять zip entries и manifest delete paths, если они содержат:

```text
C:\...
C:/...
\\server\share\...
files/C:\...
backslash in zip entry name
colon in drive-like first path segment
```

Почему это важно:

- zip path traversal на Windows может выглядеть иначе, чем на Linux;
- `Path.resolve()` полезен, но лучше отбрасывать подозрительные формы еще до вычисления destination;
- manifest paths должны быть POSIX-style, а не платформенными.

Комментарий к реализации:

- все paths в manifest считать POSIX-style;
- если path содержит `\` — fail;
- если path startswith `/` — fail;
- если первая часть содержит `:` — fail;
- если есть `..` как path segment — fail;
- destination вычислять как `(project_root / relative_path).resolve()`;
- после resolve проверять, что destination находится внутри `project_root.resolve()`;
- не использовать `ZipFile.extractall()` для применения патча;
- копировать каждый файл вручную после проверки.

## 6. Checks могут менять рабочее дерево — это надо подсвечивать

Даже если patch применился корректно, checks могут сгенерировать новые файлы или изменить lock-файлы.

Примеры:

- `npm install` меняет `package-lock.json`;
- build/test создают snapshots, coverage, generated files;
- Playwright может обновить артефакты;
- backend tests могут создать локальную БД или логи.

В v0 не нужно строить сложный include/exclude commit policy, но нужно явно фиксировать разницу.

Рекомендуемый flow:

1. сохранить `git status --porcelain` после apply;
2. run checks;
3. сохранить `git status --porcelain` после checks;
4. сравнить оба списка;
5. если после checks появились новые изменения — добавить warning в report.

Почему это важно:

- `git add -A` может прихватить больше, чем сам patch;
- пользователь должен видеть, что изменения появились не из patch files, а в результате checks;
- это поможет позже решить, нужны ли `commit.include` / `commit.exclude` в manifest.

Комментарий к реализации:

- в report добавить секции:
  - `Changed after apply`;
  - `Changed after checks`;
  - `New changes introduced by checks`;
- в v0 не блокировать commit автоматически, если checks изменили рабочее дерево;
- но если появились явно опасные файлы вроде `.env`, `*.sqlite`, `node_modules/`, `target/`, лучше не добавлять их за счет `.gitignore` и archive excludes;
- в будущем можно добавить manifest-level commit policy.

---

# Общие комментарии к `devctl` v0

## Что такое `devctl` v0

`devctl` v0 — это не универсальный devops-комбайн и не полноценный release manager.

Его задача уже и практичнее:

```text
take latest assistant patch zip
validate environment and Git state
backup current project
apply patch safely
run checks
archive result
commit
push
record what happened
```

Главная ценность v0 — убрать ручную ошибочность между чатами, архивами, локальными машинами и GitHub.

## Что v0 должен делать обязательно

- работать на чистом Python standard library;
- иметь команды:

```bash
python tools/devctl.py status
python tools/devctl.py start
```

- находить project root и workspace root;
- читать patch zip с `manifest.json`;
- проверять clean Git state;
- проверять remote sync policy;
- безопасно применять deletions;
- безопасно копировать files из `files/`;
- создавать pre/post/failed archives;
- запускать checks из manifest;
- сохранять stdout/stderr checks в logs;
- писать `report.md`;
- писать локальный `.devctl/state.json`;
- не применять уже applied patch повторно;
- commit/push делать только после успешных checks;
- при push failure ясно писать, что commit есть локально, но remote не обновлен.

## Что v0 не должен делать

- не auto-install зависимости;
- не запускать backend/frontend services;
- не делать Playwright/browser bootstrap;
- не делать mobile packaging;
- не собирать exe/AppImage/apk;
- не делать auto-rollback;
- не менять project-state/dev-log самовольно;
- не пытаться merge/rebase/pull при diverged branch;
- не чинить окружение магически.

## Минимальная модель ошибок

Для v0 достаточно таких итоговых статусов run:

- `applied` — patch применен, checks прошли, commit/push выполнены или push был disabled;
- `failed` — patch применен, но checks/commit упали;
- `push_failed` — commit создан локально, но push не прошел;
- `interrupted` — пользователь прервал процесс;
- `invalid_patch` — patch/manifest небезопасен или невалиден;
- `preflight_failed` — Git/environment/check prerequisites не прошли до применения patch.

`preflight_failed` стоит добавить сверх исходной спецификации, потому что это отдельный полезный случай: рабочее дерево не менялось, patch не применялся, но запуск не состоялся.

## Приоритет реализации

Реализовывать лучше не одним огромным куском, а слоями:

### Milestone A — skeleton/status

- `argparse`;
- discovery project/workspace;
- state registry read;
- Git status summary;
- latest patch candidate summary;
- no writes in `status`.

### Milestone B — manifest/preflight

- patch listing;
- manifest reading;
- manifest validation;
- command/cwd preflight;
- Git clean/sync checks;
- already applied detection.

### Milestone C — safe apply/archive/report

- run directory;
- manifest copy;
- pre archive;
- safe delete;
- safe copy;
- git status after apply;
- failed archive/report on errors.

### Milestone D — checks/commit/push/state

- required command logs;
- sequential checks;
- timeout support;
- post archive;
- commit with trailers;
- push;
- update state registry;
- final report.

## Короткое правило дизайна

```text
Лучше остановиться раньше и оставить понятный report,
чем попытаться быть умным и испортить рабочее дерево.
```

`devctl` должен быть скучным, предсказуемым и безопасным. Его задача — не творить магию, а сделать повторяемым тот ручной конвейер, который сейчас слишком легко забыть, перепутать или выполнить в неправильном порядке.

