# Техническое описание devctl-конвейера на чистом Python

## 1. Назначение

`devctl` — это минималистичный локальный конвейер применения патчей для проекта `p2p_planner`.

Он должен автоматизировать рутину, которая сейчас выполняется вручную:

- взять последний patch zip;
- применить его к проекту;
- учесть удаления файлов/каталогов из manifest;
- прогнать проверки;
- сохранить логи;
- создать резервные и итоговые архивы;
- сделать commit;
- сделать push;
- не потерять состояние между машинами.

Инструмент делается под текущую модель разработки: ассистент генерирует patch zip с `manifest.json`, пользователь кладет его в `patches`, запускает одну команду.

## 2. Нефункциональные требования

### 2.1. Pure Python

`devctl` должен работать только на стандартной библиотеке Python.

Запрещено требовать:

- `pip install`;
- сторонние Python-пакеты;
- Poetry;
- virtualenv;
- системно установленные Python-зависимости, кроме самого Python.

Разрешены модули стандартной библиотеки:

- `argparse`;
- `json`;
- `hashlib`;
- `pathlib`;
- `zipfile`;
- `shutil`;
- `subprocess`;
- `datetime`;
- `os`;
- `sys`;
- `signal`;
- `threading`;
- `time`;
- `urllib.request` для будущих readiness checks.

### 2.2. Кроссплатформенность

Целевые ОС:

- Windows;
- Linux.

MacOS можно не считать основной целью, но не стоит намеренно ломать совместимость.

Основные правила:

- для путей использовать `pathlib.Path`;
- в manifest хранить пути в POSIX-style;
- не полагаться на bash-only возможности;
- учитывать `npm.cmd`/`cargo.exe` через `shutil.which`;
- stdout/stderr писать с безопасной кодировкой `utf-8` с replacement для ошибок;
- не использовать symlink-specific behavior в v0.

### 2.3. Минимальный UX

Команды v0:

```bash
python tools/devctl.py status
python tools/devctl.py start
```

`status` ничего не меняет.

`start` запускает весь конвейер.

## 3. Ожидаемая структура workspace

```text
p2p_workspace/
  patches/
  archives/
  p2p_planner/
    backend/
    frontend/
    docs/
    tools/
      devctl.py
```

`archives` — предпочтительное имя.

`arhives` можно поддержать как legacy alias, если такая папка уже существует. Новые архивы желательно писать в `archives`.

## 4. Где лежит devctl

Файл инструмента:

```text
p2p_planner/tools/devctl.py
```

Скрипт сам должен уметь определить:

- project root: родительский каталог, содержащий `.git`, `backend`, `frontend` или другие признаки проекта;
- workspace root: родитель project root, содержащий `patches` и `archives`.

Если структура не найдена, `devctl` должен вывести понятную ошибку.

## 5. Формат patch zip

Patch zip должен иметь структуру:

```text
patch_YYYYMMDD_HHMMSS_slug.zip
  manifest.json
  files/
    docs/...
    backend/...
    frontend/...
  README.patch.md            optional
```

`files/` накладывается поверх project root.

Пример:

```text
files/docs/project-state.md
```

становится:

```text
p2p_planner/docs/project-state.md
```

## 6. Manifest v1

Минимальные обязательные поля:

```json
{
  "formatVersion": 1,
  "patchId": "unique-patch-id",
  "title": "Human title",
  "summary": "What this patch does",
  "apply": {
    "filesRoot": "files",
    "delete": []
  },
  "checks": [],
  "commit": {
    "enabled": true,
    "message": "chore: example"
  },
  "push": {
    "enabled": true,
    "remote": "origin",
    "branch": "main"
  }
}
```

Рекомендуемые поля:

- `kind`;
- `createdAt`;
- `base.branch`;
- `base.expectedHead`;
- `archive.nameSlug`;
- `checks[].requiredCommands`;
- `checks[].timeoutSeconds`;
- `setup` reserved;
- `services` reserved.

## 7. State registry

Служебный файл:

```text
p2p_workspace/.devctl/state.json
```

Назначение:

- помнить примененные patch zip;
- не применять один и тот же patch дважды;
- показывать последний успешный/упавший прогон;
- хранить ссылки на archive dirs и commit sha.

Пример:

```json
{
  "version": 1,
  "runs": [
    {
      "patchId": "2026-04-30-release-workflow-automation",
      "patchFile": "patch_20260430_231502_release-workflow.zip",
      "patchSha256": "7f3a9c...",
      "status": "applied",
      "startedAt": "2026-04-30T23:15:02+07:00",
      "finishedAt": "2026-04-30T23:19:48+07:00",
      "commitSha": "abc1234",
      "archiveDir": "archives/20260430_231502_release-workflow_7f3a9c"
    }
  ]
}
```

Statuses:

- `applied`;
- `failed`;
- `push_failed`;
- `interrupted`;
- `invalid_patch`.

## 8. Команда status

`status` должен вывести:

- project root;
- workspace root;
- current git branch;
- last commit sha/message;
- git dirty/clean;
- untracked files summary;
- ahead/behind относительно upstream;
- latest patch candidate;
- whether latest patch is already applied;
- latest archive folder;
- latest failed run, if any.

`status` не должен:

- применять патчи;
- создавать архивы;
- запускать checks;
- делать commit;
- делать push;
- менять state.json.

## 9. Команда start

`start` выполняет полный конвейер.

### 9.1. Последовательность

1. Discover workspace/project.
2. Load state registry.
3. Find latest unapplied patch zip by file mtime.
4. Compute patch SHA-256.
5. Open zip and read `manifest.json`.
6. Validate manifest.
7. Validate Git state.
8. Validate branch/ahead/behind.
9. Create run archive directory.
10. Save manifest copy and git-status-before log.
11. Create pre-apply project archive.
12. Apply deletions from manifest.
13. Apply files from `filesRoot` safely.
14. Save git diff/status after apply.
15. Check required commands.
16. Run checks.
17. If checks pass:
    - create post-apply project archive;
    - `git add -A`;
    - create commit;
    - push;
    - update state registry as `applied`;
    - write report.
18. If checks fail:
    - create failed-state project archive;
    - do not commit;
    - do not push;
    - update state registry as `failed`;
    - write report.

### 9.2. Нет нового патча

If no unapplied patch exists:

- do nothing;
- print status-like summary;
- do not create archive;
- do not commit;
- do not push.

### 9.3. Патч уже применён

If latest patch SHA-256 is already `applied`:

- do not reapply;
- show previous run info;
- do not create duplicate archive.

## 10. Правила работы с Git

### 10.1. Обязательное чистое рабочее дерево

Before applying patch:

- `git status --porcelain` must be empty;
- if not empty — stop.

### 10.2. Синхронизация с remote

Run:

```bash
git fetch --prune
```

Then determine ahead/behind.

If behind remote:

- v0: stop and ask user to sync manually;
- v1 may support automatic `git pull --ff-only` from clean worktree.

If diverged:

- stop;
- do not merge/rebase automatically.

If ahead before applying patch:

- stop or warn strongly, depending on policy;
- preferred v0 behavior: stop, because push discipline is already broken.

### 10.3. Commit и push

Commit only if:

- patch applied;
- checks passed;
- there are actual changes;
- commit.enabled is true.

Push only if:

- commit succeeded;
- push.enabled is true.

If push fails:

- status: `push_failed`;
- report must clearly say commit exists locally but is not on remote.

## 11. Правила архивов

Each run gets a unique run directory:

```text
archives/YYYYMMDD_HHMMSS_slug_shortpatchsha/
  pre_p2p_planner_YYYYMMDD_HHMMSS_before_slug.zip
  post_p2p_planner_YYYYMMDD_HHMMSS_after_slug_gitsha.zip
  failed_p2p_planner_YYYYMMDD_HHMMSS_after_failed_slug.zip
  logs/
    manifest.json
    git-status-before.log
    git-status-after-apply.log
    git-status-after-checks.log
    check-*.log
  report.md
```

For successful run:

- `pre_...zip`;
- `post_...zip`;
- logs;
- report.

For failed run:

- `pre_...zip`;
- `failed_...zip`;
- logs;
- report.

Archives must not overwrite existing files. On collision, append numeric suffix.

## 12. Archive excludes

Starting with `devctl` v0.2, archive creation has one extra release-specific trimming rule: keep the `release/` directory structure, but omit heavyweight release payloads from devctl snapshots by default. This means `release/**/*.zip` and `release/**/*.exe` are replaced in the archive by small placeholder text files such as `тут_был_zip_архив.txt` and `тут_был_экзешник.txt`. The working tree is not modified. A patch manifest can opt out with `archive.includeReleasePayloads: true` when a full payload snapshot is explicitly required.

Default excludes:

```text
.git/
.devctl/tmp/
target/
node_modules/
dist/
build/
coverage/
logs/
tmp/
.env
.env.*
*.db
*.sqlite
*.sqlite3
```

Exception:

```text
.env.example
```

should be allowed.

## 13. Правила безопасного применения

### 13.1. Safe file copy

For every zip entry under `filesRoot`:

1. reject directories/files with absolute paths;
2. reject paths containing `..`;
3. compute destination under project root;
4. resolve path;
5. verify destination remains inside project root;
6. create parent directories;
7. write file.

Never extract zip directly into project root.

### 13.2. Safe delete

For every manifest delete entry:

1. path must be relative;
2. path must not contain `..`;
3. resolved target must be inside project root;
4. target must not be project root;
5. target must not be `.git`, `.devctl`, `target`, `node_modules`;
6. if directory, require `recursive: true`;
7. if missing and `required: false`, warn but continue;
8. if missing and `required: true`, fail.

## 14. Checks

Checks are defined in manifest:

```json
{
  "name": "frontend build",
  "cwd": "frontend",
  "command": "npm run build",
  "timeoutSeconds": 300,
  "requiredCommands": ["npm"]
}
```

v0 behavior:

- run checks sequentially;
- use shell execution for command string;
- cwd is relative to project root;
- save stdout/stderr to a log file;
- fail on non-zero exit code;
- fail on timeout;
- stop at first failed check.

## 15. Dependency/setup policy

`devctl` itself must not require dependencies.

Project checks may require tools. In v0:

- `devctl` detects missing required commands;
- if missing, fail with clear message;
- do not auto-install unless manifest has future `setup` section and implementation supports it.

Future v1 setup example:

```json
{
  "setup": [
    {
      "name": "Install frontend dependencies",
      "cwd": "frontend",
      "command": "npm install",
      "runWhen": "missing_node_modules"
    }
  ]
}
```

Auto-installation should be explicit, logged and preferably confirmable.

## 16. Services policy

v0 does not auto-start backend/frontend services.

Future v2 can support:

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

v2 must handle:

- process startup;
- readiness timeout;
- logs;
- graceful shutdown;
- Windows process tree behavior;
- port already occupied.

## 17. Report

Each run writes `report.md`.

Report includes:

- patch id/title/sha;
- start/end time;
- project root;
- git branch/head before;
- apply summary;
- deleted files;
- copied files count/list;
- checks and results;
- archive paths;
- commit sha if any;
- push result;
- final status;
- next suggested action.

## 18. Error handling

### Invalid patch

- no apply;
- no commit;
- no push;
- report status `invalid_patch`.

### Check failed

- failed-state archive;
- no commit;
- no push;
- report status `failed`.

### Commit failed

- post archive may exist;
- no push;
- report status `failed`;
- include git commit stderr.

### Push failed

- commit exists locally;
- report status `push_failed`;
- state registry marks push_failed;
- status must warn on next run.

### Interrupted

- catch KeyboardInterrupt;
- best-effort report;
- no commit;
- no push;
- status `interrupted`.

## 19. Implementation milestones

### Milestone 0 — docs and examples

- risks document;
- dev-log example;
- project-state example;
- manifest example;
- this technical specification.

### Milestone 1 — devctl v0 skeleton

- argument parser;
- workspace discovery;
- status command;
- state registry read/write;
- patch detection;
- manifest parsing.

### Milestone 2 — safe apply and archives

- pre archive;
- safe delete;
- safe copy;
- failed/post archive;
- report generation.

### Milestone 3 — checks and Git automation

- required command detection;
- checks execution;
- logs;
- commit;
- push;
- final state registry.

### Milestone 4 — environment improvements

- setup steps;
- optional auto pull fast-forward;
- project-state/dev-log integration.

### Milestone 5 — services

- backend/frontend auto-start;
- readiness checks;
- smoke/browser tests with service logs.

## 20. Acceptance criteria for v0

v0 is acceptable when:

- `python tools/devctl.py status` works from project root;
- `python tools/devctl.py start` finds latest unapplied patch;
- already applied patch is not applied again;
- dirty worktree blocks start;
- patch with delete entries can remove files safely;
- patch files are copied safely from `files/`;
- pre archive is created before modification;
- checks run and logs are saved;
- failed checks prevent commit/push;
- successful checks create post archive, commit and push;
- report.md is written for every meaningful run;
- archives exclude `.git`, `target`, `node_modules`, `.env`, local DB files;
- works on Windows and Linux using only Python standard library.
