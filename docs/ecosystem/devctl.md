# devctl в экосистеме

## Решение

devctl играет две роли одновременно:

1. **Гостевая копия.** Истина о devctl живёт в отдельном репозитории
   [devctl-universal](https://github.com/Pacifica123/devctl-universal): devctl
   универсален и обслуживает все проекты владельца, не только экосистему.
   `devctl/` здесь — копия upstream на конкретном коммите, чтобы патчи и UTS
   видели ту же версию, что установлена у владельца. Сейчас:
   **upstream `50f4324`, версия 0.9.0**. Правки devctl делаются патчем в
   devctl-universal, а сюда приходят отдельным патчем «devctl/ = upstream
   `<sha>`», который копирует файлы без изменений.
2. **Связующий конвейер.** Корень репозитория — devctl-workspace
   (`.devctl/workspace.json`, `projectDir: "."`). Все патчи экосистемы идут
   одним потоком через `devctl start`, и `devctl zip` собирает историю всей
   экосистемы в один архив для нейросети.

Именно второй роли не хватало раньше: у каждого проекта был свой workspace и
своя история, и патч не видел соседей.

## Рабочая схема

```text
workspace (корень репозитория)
  .devctl/workspace.json   отслеживается в git
  .devctl/state.json       локальный журнал, в .gitignore
  patches/ archives/ UserTestSpace/   локальные, в .gitignore
  web/ mobile/ abl/ devctl/ docs/ board/ tools/
```

```bash
python3 devctl/devctl.py self install     # один раз
cd <корень репозитория>
devctl workspace register . --id p2p-kanban --name "p2pKanban ecosystem"
devctl plan
devctl start
devctl zip
```

Команды devctl для экосистемы запускаются **из корня**. Внутри `devctl/` лежит
собственный `.devctl/workspace.json` направления devctl, и поиск вверх от
`devctl/` найдёт его первым.

## Патч в монорепозитории

Пути в `files/` считаются от корня репозитория: `web/README.md`,
`mobile/src/...`, `board/board.json`. Проверки запускаются с `cwd` нужного
направления, поэтому собственные команды направлений работают без изменений:

```json
"checks": [
  {"name": "Доска экосистемы", "cwd": ".", "command": "python -B tools/ecosystem/check_board.py --require-changed"},
  {"name": "web: unit-тесты инструментов", "cwd": "web", "command": "python -B -m unittest discover -s tools -p \"test_*.py\""},
  {"name": "mobile: сборщик APK", "cwd": "mobile", "command": "node --test scripts/apk-commands.test.mjs"},
  {"name": "abl: детерминированные проверки", "cwd": "abl", "command": "python3 -B tools/check_uts_cache_recovery.py"},
  {"name": "devctl: тесты", "cwd": "devctl", "command": "python -B -m unittest discover -s tests"}
]
```

Шаблон манифеста — [patch-manifest.template.json](patch-manifest.template.json).
В него входят только проверки затронутых направлений; проверка доски нужна
всегда.

## Ограничения devctl, важные для монорепозитория

| Ограничение | Следствие |
|---|---|
| Патч не может принести `.env` и `.env.*`; шаблоны `.env.example`, `.env.sample`, `.env.template`, `.env.dist` можно (с 0.9.0) | `web/backend/.env.example` и `web/frontend/.env.example` меняются патчем как обычные файлы |
| `apply.delete` не удаляет пути с `target`, `node_modules`, `.devctl` | удаление таких каталогов внутри направлений делается вручную |
| `start` останавливается, если `git status` показывает `patches`, `archives`, `UserTestSpace`, `node_modules`, `target`, `*.db` | сборки направлений должны оставаться в их `.gitignore`; проверки не должны оставлять артефактов |
| `cwd` проверки должен существовать после наложения файлов (с 0.9.0; раньше — до) | проверка может запускаться из каталога, который создаёт сам патч |
| `base.expectedHead` проверяется (с 0.9.0) | патч, собранный против другого HEAD, останавливается до изменений; указывайте его всегда |
| Откату нужен хотя бы один коммит | инициирующий коммит создаётся напрямую git, не через `devctl start` |

## Пачки патчей (devctl 0.9.0)

Несколько патчей, которые нужно применить вместе и по порядку, приходят одной
пачкой `batch_<время>_<имя>.zip` ([devctl/docs/batch.md](../../devctl/docs/batch.md)).
Опора пачки — реестр workspace машины, поэтому в `batch.json` workspace
называется по id из реестра владельца (`devctl workspace list --for-agent`), а у
первого патча стоит `expectedHead`.

```bash
devctl batch plan  batch_….zip     # ничего не меняет; проверяет всю пачку
devctl batch start batch_….zip     # применяет по порядку, push только в конце
devctl batch status                # где остановилась последняя пачка
devctl batch reset --yes           # откатить неотправленную пачку
```

Для экосистемы это значит:

- **ревизии доски идут подряд**: каждый патч пачки поднимает `boardRevision`
  ровно на 1 и ссылается на предыдущий через `base.after`;
- **правило «одно направление на патч» сохраняется**: пачка — это ряд обычных
  патчей, а не один большой; порядок внутри пачки следует порядку обновления
  контрактов (web-узлы → mobile → abl);
- **push в конце**: если упал пятый патч, первые четыре остаются локальными
  коммитами, а remote не видит половины изменения.

## Связь с доской

Доска и devctl связываются по `patchId`: каждый патч оставляет на доске
комментарий с `patchId` к карточке, которую двигает (см.
[development.md](development.md)). Web уже умеет принимать devctl receipts
(`web/docs/integrations/devctl-v2.md`); перевод корневой доски на эти receipts —
шаг пути интеграции, а не часть инициирующего патча.
