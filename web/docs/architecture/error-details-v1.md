# Подробности ошибки на web-узле и в web UI

Реализация контракта [error-report/1](../../../contracts/error-report/1/SPEC.md)
в web (патч `2026-10-07-web-error-details`).

## Узел

- `src/http/error_report.rs` — внешний слой всего роутера:
  - у каждого запроса заранее есть `error_id` (UUID v7) в span журнала, поэтому
    строка «database error» и id, который скопировал человек, совпадают;
  - ответ 5xx получает `errorId` в теле `{"error": {...}}` и заголовок
    `x-p2p-error-id`; тело не в формате ошибки оборачивается в него;
  - паника обработчика превращается в 500 с `errorId` (раньше соединение
    обрывалось, и шлюз отвечал 502 без тела — так выглядела остановка копии
    доски 2026-10-06);
  - каждый ответ несёт `x-p2p-kanban-node: <версия>; build=<…>; commit=<…>`.
- `build` и `commit` берутся из `P2PKANBAN_BUILD` (тег образа) и
  `P2PKANBAN_SOURCE_REVISION`; compose передаёт оба. Их же показывает `/health`.
- Найти строку журнала по id: `python bootstrap.py logs` и поиск по `error_id`.

## Web UI

- `src/shared/errorReport/report.ts` — порт `redact`, `truncate`,
  `build_report`, `render_report`, `parse_node_header` из эталона; тест
  `src/test/unit/shared/errorReport.test.ts` читает векторы `contracts/`.
- `journal.ts` — кольцевой буфер на 200 строк в памяти: запросы к API,
  `console.warn/error`, необработанные ошибки; последний заголовок узла и
  последний неудачный запрос. На диск и в сеть ничего не уходит.
- `ErrorDetails` — кнопка «Скопировать подробности». Она есть в каждом
  `ErrorState` и рядом с сообщениями об ошибке на экранах сети, кольца,
  обновления узла и напоминаний. Если ошибка не передана, отчёт берёт последний
  неудачный запрос (до 2 минут). Узел, открытый по http в локальной сети, не
  даёт `navigator.clipboard`: тогда пробуется `execCommand('copy')`, а если и он
  не сработал, текст показывается для ручного выделения.
- Сборка web UI знает свой коммит (`VITE_SOURCE_REVISION`) и тег образа
  (`VITE_BUILD_ID`); в отчёте видно и версию UI, и версию узла, с которым он
  говорил.

## Патч сборки

Внизу боковой панели под версиями Web и Backend стоит строка
«патч N · <patchId>»: из какого devctl-патча собран этот
web UI. Правило общее для клиентов: `board/README.md`, «Номер патча в версии
клиентов».

- `tools/container_bootstrap.py` находит патч так: `P2PKANBAN_PATCH_ID` и
  `P2PKANBAN_PATCH_REVISION`, затем `BUILD_PATCH.json` в корне исходников
  узла, затем `board/board.json` непосредственно над `web/`. Дальше вверх не
  ищет: релизные копии `.dev-bootstrap/releases/*/source` лежат внутри
  checkout и не должны брать его более новую доску.
- Обновление из GitHub берёт доску из архива коммита до того, как от него
  остаётся только `web/`, и пишет `BUILD_PATCH.json` в релизную копию.
  Отпечаток исходников (`source_fingerprint`) файл не меняет.
- Compose передаёт пару в сборку образа web как `VITE_PATCH_ID` и
  `VITE_PATCH_REVISION`; `vite.config.ts` вписывает её в бандл, а в checkout
  без этих переменных читает доску над `web/` сам. Перезапуск без пересборки
  (`--no-build`) номер не меняет: он в образе.
- Backend номер не знает: `/health` и `x-p2p-kanban-node` прежние.
- Проверки: `python -B tools/test_build_patch.py`, `npx vitest run
  src/test/unit/shared/buildPatch.test.ts`.
