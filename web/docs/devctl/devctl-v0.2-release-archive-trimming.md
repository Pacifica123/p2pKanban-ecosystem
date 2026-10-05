# devctl v0.2 — уменьшение release snapshots

- Статус: действующее правило встроенного `tools/devctl.py`

## Проблема

Каталог `release/` полезен, но может содержать большие ZIP и Windows `.exe`.
Если копировать их в каждый pre/post/failed snapshot, `archives/` быстро
разрастается.

## Решение

По умолчанию структура `release/` сохраняется, но:

```text
release/**/*.zip
release/**/*.exe
```

заменяются маленькими поясняющими placeholders. Рабочая копия не изменяется и
реальные файлы не удаляются.

Редкий opt-out:

```json
{
  "archive": {
    "includeReleasePayloads": true
  }
}
```

## Что остаётся

Исходники, документация, конфигурация, миграции и release metadata продолжают
попадать в snapshot. Обычные исключения `.git`, `target`, `node_modules`,
`dist`, `.env` и локальных БД сохраняются.

## Проверка

```bash
python -m py_compile tools/devctl.py
python tools/devctl.py status
```

Ручная проверка должна подтвердить, что snapshot содержит placeholders, а не
тяжёлые payload.

