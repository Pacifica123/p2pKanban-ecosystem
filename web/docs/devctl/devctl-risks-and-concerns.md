# Devctl patch conveyor — риски, опасения и защитные меры

Документ фиксирует риски для будущего конвейера применения патчей `devctl`, чтобы при реализации не забыть важные детали.

## 1. Цель конвейера

`devctl` нужен не как универсальный devops-инструмент, а как производственная линия под текущий стиль разработки проекта:

1. ассистент выдает zip-патч с `manifest.json`;
2. пользователь кладет патч в `p2p_workspace/patches`;
3. пользователь запускает одну команду `python tools/devctl.py start`;
4. скрипт делает резервную копию текущего проекта;
5. применяет удаления и новые/измененные файлы;
6. прогоняет проверки из manifest;
7. при успехе архивирует результат, коммитит и пушит;
8. при ошибке не коммитит и не пушит, но сохраняет failed-state и логи.

## 2. Главный принцип безопасности

Скрипт имеет право применять патч только из чистого и понятного состояния Git.

Перед применением патча `start` должен остановиться, если:

- есть незакоммиченные изменения;
- есть важные untracked-файлы;
- локальная ветка отстала от remote;
- локальная ветка разошлась с remote;
- текущий каталог не похож на ожидаемый workspace;
- невозможно прочитать manifest;
- прошлый прогон завершился ошибкой и рабочее дерево все еще грязное.

Исключение может быть только осознанным ручным режимом будущей версии, но не в v0/v1.

## 3. Требование: чистый Python без внешних зависимостей

Скрипт должен работать на стандартной библиотеке Python.

Нельзя требовать:

- `pip install ...`;
- Poetry;
- virtualenv;
- сторонние Python-пакеты;
- platform-specific Python libraries.

Разрешены только модули стандартной библиотеки, например:

- `argparse`;
- `json`;
- `hashlib`;
- `pathlib`;
- `shutil`;
- `zipfile`;
- `subprocess`;
- `datetime`;
- `os`;
- `sys`;
- `signal`;
- `threading`;
- `urllib.request` для readiness HTTP-проверок в будущей версии с сервисами.

Причина: инструмент должен снижать трение входа в проект. Для запуска должно хватать установленного Python и папки workspace.

## 4. Риск: проверки сами требуют зависимостей

Даже если сам `devctl` без зависимостей, проверки проекта могут требовать внешние инструменты:

- Rust/Cargo для backend;
- Node/npm/npx для frontend;
- Playwright browser binaries;
- pytest или другие Python test tools;
- локальную БД;
- env-переменные;
- занятые или свободные порты.

### Защитная мера v0

В v0 `devctl` не должен обещать магически подготовить всю среду.

Он должен:

- проверить наличие команд из manifest через `shutil.which`;
- если команда отсутствует — остановиться до применения патча или перед checks, в зависимости от стадии;
- сохранить понятный report;
- не коммитить и не пушить;
- в logs/report указать, какой инструмент отсутствует.

### Защитная мера v1+

В manifest можно добавить `setup`-шаги, но они должны быть явными:

```json
{
  "setup": [
    {
      "name": "Install frontend dependencies",
      "cwd": "frontend",
      "command": "npm install",
      "runWhen": "missing_node_modules"
    },
    {
      "name": "Install Playwright browsers",
      "cwd": "frontend",
      "command": "npx playwright install",
      "runWhen": "missing_playwright_browsers"
    }
  ]
}
```

Важно: автоустановка зависимостей может быть удобной, но она опаснее обычных проверок, потому что меняет окружение. Поэтому setup-шаги должны быть отражены в manifest и логах.

## 5. Риск: npx/npm что-то доустанавливают

Frontend-команды могут вести себя неоднозначно:

- `npx` может скачивать пакеты;
- `npm install` может изменить `package-lock.json`;
- разные версии Node/npm могут давать разные результаты;
- Playwright может требовать установку браузеров.

### Защитная мера

Для v0:

- `devctl` только запускает команды, указанные в manifest;
- все stdout/stderr сохраняются в logs;
- если команда меняет lock-файлы, это остается в рабочем дереве и видно в Git diff;
- commit делается только после успешных checks и с учетом всех измененных файлов.

Для v1:

- добавить режим `prepareEnvironment` в manifest;
- явно логировать все setup-команды;
- возможно, требовать подтверждение перед setup, если команда может скачивать зависимости.

## 6. Риск: pytest не установлен

Python smoke/test scripts могут зависеть от pytest, requests или других пакетов, которых нет в глобальной среде.

### Защитная мера

Варианты:

1. предпочитать smoke-скрипты на чистом Python standard library;
2. если нужен pytest — manifest должен явно иметь setup/check:

```json
{
  "checks": [
    {
      "name": "Python smoke",
      "cwd": ".",
      "command": "python tests/smoke_core_api.py",
      "requires": ["python"]
    }
  ]
}
```

3. если нужна установка Python-зависимостей — это отдельный setup-шаг, а не скрытая магия.

## 7. Риск: Windows/Linux различия

Python `pathlib`, `shutil`, `zipfile`, `subprocess` в целом кроссплатформенные, но отличия есть.

Проблемные зоны:

- разделители путей `/` и `\\`;
- executable names: `npm` vs `npm.cmd`, `cargo` vs `cargo.exe`;
- shell quoting;
- кодировка stdout/stderr;
- права на исполнение файлов в zip;
- line endings CRLF/LF;
- длинные пути Windows;
- занятые файлы на Windows;
- удаление каталогов, если файл открыт процессом;
- симлинки;
- case sensitivity: Linux чувствителен к регистру, Windows обычно нет.

### Защитная мера

- В manifest paths всегда писать POSIX-style: `frontend/src/main.tsx`.
- Внутри скрипта использовать `pathlib.Path`.
- Не собирать команды через shell string там, где можно использовать list args.
- Но для простоты manifest v0 может хранить command как строку, а `devctl` запускать ее через shell с явным логированием.
- Все пути нормализовать и проверять, что они остаются внутри project root.
- Не поддерживать symlinks в v0 или распаковывать их как обычные файлы с предупреждением.
- Архивы создавать через `zipfile`, исключая build-мусор.
- При удалении использовать safe-delete, запрещающий выход за project root.

## 8. Риск: path traversal в patch zip

Патч может содержать пути вроде:

- `../outside.txt`;
- `/absolute/path`;
- `C:\\Users\\...`;
- `files/../../.git/config`.

### Защитная мера

Перед распаковкой каждого файла:

1. вычислить destination path;
2. сделать `.resolve()`;
3. проверить, что destination находится внутри project root;
4. если нет — остановить применение.

Нельзя распаковывать zip напрямую в project root без проверки каждого entry.

## 9. Риск: manifest удаляет лишнее

Удаления нужны, потому что zip-патч из новых/измененных файлов не умеет выразить удаление старых файлов.

Но удаление опасно.

### Запрещенные удаления

Скрипт должен запрещать удалять:

- пустой path;
- `.`;
- project root;
- абсолютные пути;
- пути с `..`;
- `.git`;
- `.devctl`;
- `target`;
- `node_modules`;
- parent-каталоги workspace;
- любые пути вне project root.

### Разрешенные удаления

Разрешать только конкретные файлы/каталоги внутри проекта:

```json
{
  "delete": [
    { "path": "docs/old-doc.md" },
    { "path": "frontend/src/legacy", "recursive": true }
  ]
}
```

Если path не существует, это не обязательно ошибка. Лучше warning: файл уже отсутствует.

## 10. Риск: повторный запуск одного и того же патча

Без защиты повторный `start` может:

- повторно применить тот же patch;
- повторно удалить файлы;
- создать пустой commit;
- создать дублирующий archive;
- запутать историю.

### Защитная мера

Хранить state registry:

```text
p2p_workspace/.devctl/state.json
```

В нем сохранять:

- `patchSha256`;
- `patchId`;
- status: `applied`, `failed`, `push_failed`, `interrupted`;
- timestamp;
- commit sha, если есть;
- archive directory.

Если patchSha256 уже `applied`, повторный start должен быть no-op.

## 11. Риск: нет новых патчей

Поведение:

- не создавать archive;
- не делать commit;
- не запускать checks;
- вывести status;
- сказать, какой patch был применен последним.

## 12. Риск: прошлый прогон упал

Если прошлый прогон завершился `failed`, рабочее дерево, скорее всего, грязное.

Поведение:

- `status` показывает failed run и путь к логам;
- `start` не применяет следующий patch поверх грязного состояния;
- пользователь либо откатывает изменения, либо просит fixing patch, либо вручную коммитит/чистит состояние.

## 13. Риск: commit создан, push не прошел

Причины:

- нет интернета;
- нет авторизации GitHub;
- remote отклонил push;
- branch protection;
- remote обновился между check и push.

Поведение:

- run status: `push_failed`;
- post archive уже можно создать;
- report должен явно сказать: commit есть локально, push не выполнен;
- следующий `status` должен показывать commits ahead of origin.

## 14. Риск: локальная машина отстала от GitHub

Если local branch behind remote:

- безопасно делать `git pull --ff-only`, только если дерево чистое;
- в v0 лучше остановиться и явно попросить пользователя выполнить sync;
- в v1 можно добавить auto fast-forward pull перед применением patch.

## 15. Риск: локальная и remote ветка разошлись

Если branch diverged:

- не применять patch;
- не пытаться merge/rebase автоматически;
- показать инструкцию и git status;
- создать diagnostic report при необходимости.

## 16. Риск: untracked файлы

Untracked могут быть:

- полезными новыми файлами;
- мусором;
- локальными логами;
- забытым важным кодом.

Поведение v0:

- если есть untracked вне ignore/exclude — остановиться;
- показать список;
- не применять patch.

## 17. Риск: секреты в архивах

Архивы не должны включать:

- `.git/`;
- `.env`;
- `.env.*`, кроме `.env.example`;
- `target/`;
- `node_modules/`;
- `dist/`;
- `build/`;
- local database files: `*.db`, `*.sqlite`, `*.sqlite3`;
- временные logs/tmp/cache;
- IDE folders при необходимости.

## 18. Риск: архивы слишком большие

Причины:

- случайно попал `target`;
- попал `node_modules`;
- попали Playwright browser binaries;
- попали generated assets.

Защитная мера:

- exclude list;
- report с размером архива;
- предупреждение, если archive size выше разумного порога.

## 19. Риск: Ctrl+C / аварийное завершение

Поведение:

- ловить KeyboardInterrupt;
- записывать report со статусом `interrupted`;
- не commit;
- не push;
- если patch уже частично применен — оставить рабочее дерево как есть и сохранить diagnostic archive, если возможно.

## 20. Риск: проверки зависят от запущенных сервисов

В v0 это не решается автоматически.

В v1+ manifest может поддерживать `services`:

```json
{
  "services": [
    {
      "name": "backend",
      "cwd": "backend",
      "command": "cargo run",
      "readyUrl": "http://127.0.0.1:18080/api/v1/health",
      "timeoutSeconds": 60
    }
  ]
}
```

Риски services:

- порт занят;
- процесс не завершился;
- child processes на Windows;
- лог слишком большой;
- readiness URL отвечает не сразу;
- backend требует БД/env.

В v0 services не включать, чтобы не раздуть реализацию.

## 21. Риск: manifest не соответствует patch content

Например manifest заявляет `filesRoot: files`, но такой папки нет.

Поведение:

- остановиться до применения;
- report: invalid manifest/patch;
- не создавать pre/post archives, кроме diagnostic report при необходимости.

## 22. Риск: patch рассчитан на другую базовую версию

Manifest может содержать `base`:

```json
{
  "base": {
    "branch": "main",
    "requiredCleanWorktree": true,
    "expectedHead": "optional-sha"
  }
}
```

В v0 `expectedHead` можно считать advisory: предупреждать, но не обязательно блокировать.

В критичных патчах можно сделать `expectedHeadPolicy: required`.

## 23. Риск: автокоммитит лишнее

После checks в рабочем дереве могут появиться generated files.

Защитная мера:

- перед commit показать staged/changed files в report;
- уважать `.gitignore`;
- не добавлять excluded artifacts;
- использовать `git add -A`, но только после excludes и после понятного report;
- в будущей версии разрешить manifest `commit.include` / `commit.exclude`.

## 24. Риск: dev-log/project-state автозапись конфликтует с патчем

Если скрипт сам меняет docs, он может создать лишние diffs.

Защитная мера v0:

- не автогенерировать сложные изменения docs;
- максимум писать отдельный report в archives;
- project-state/dev-log обновлять патчами или отдельной будущей функцией.

## 25. Рекомендованный порядок реализации

### v0

- pure Python;
- команды `status` и `start`;
- workspace discovery;
- latest unapplied patch detection;
- manifest parsing;
- safe delete;
- safe copy from `files/`;
- pre archive;
- checks as shell commands;
- logs/report;
- post/failed archive;
- commit/push only on success;
- patch state registry.

### v1

- setup steps;
- optional auto fast-forward pull;
- better check prerequisites;
- dev-log/project-state append;
- richer manifest validation.

### v2

- services auto-start;
- readiness checks;
- smoke/browser tests with backend/frontend logs;
- optional environment bootstrap.
