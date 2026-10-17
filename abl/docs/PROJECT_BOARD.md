# Доска проекта в abl (`p2p-kanban-project-board/1`)

- Дата: 2026-10-17, патч `2026-10-17-abl-project-board`
- Контракт: `contracts/project-board/1/` в корне монорепозитория; решение — E-ADR-003 экосистемы

## Что видит человек

Под полосой LAN-моста — свёрнутый блок **«Доска проекта · только чтение»**. Это доска,
на которой p2pKanban ведёт свою разработку. Раскрыл — видны колонки, карточки с
метками, чек-листами и комментариями (по щелчку на заголовок). Менять ничего нельзя.
В заголовке блока — «Ревизия N · патч · из сборки».

## Откуда доска

Только `build`: `src-tauri/assets/project-board.json`, вшит в бинарник через
`include_str!` (`src-tauri/src/domain/project_board.rs`). Копию обновляет
`python -B tools/ecosystem/project_board.py vendor abl`, проверяет
`project_board.py check`. Сеть не нужна.

С узла abl доску не берёт: связи abl с web-узлом пока нет. Когда она появится, abl
добавит кандидатов `cache` и `node` по тому же правилу выбора (старшая ревизия), как
mobile. Если UI запущен с web-транспортом, `GET /project-board` уходит на узел и
показывается «с узла».

Доска не пишется в базу профиля, не попадает в roaming, relay, связку ключей и список
пространств, поэтому подключение устройств её не размножает.

## Код

- `src-tauri/src/domain/project_board.rs` — сводка и коды отказа по контракту; тесты на
  векторах `contracts/project-board/1/vectors/summary.json` и на вшитой копии.
- `desktop_api_project_board` (`src-tauri/src/desktop_api.rs`) — байты и сводка, строками,
  как остальные DTO.
- `src/features/projectBoard/` — `api.ts`, `model.ts` (вид доски), `ProjectBoardPanel.tsx`.

## Приёмка на Arch

1. `cargo test` в `src-tauri` (UTS): проходят `project_board_*`.
2. Запустить abl без сети, раскрыть «Доска проекта»: ревизия совпадает с
   `board/board.json` того патча, карточки открываются, кнопок изменения нет.
3. Список Workspaces не изменился.
