# Release gates v2

- Статус: реализовано; документ описывает действующий контракт

`release-gates` запускает все безопасные проверки, не останавливаясь после
первого сбоя, классифицирует результаты и собирает компактный bundle.

## Семейства проверок

| Семейство | Примеры |
|---|---|
| Инструмент | self-check, diagnose |
| Backend | Cargo tests, отдельные DB tests |
| Smoke | два последовательных Python API smoke |
| Frontend | dependency prepare, build, unit/integration |
| UIX | mocked и real-backend сценарии |
| Документация | README, версия, limitations, release files |
| Clean machine | dry/deps/runtime sandbox |

## Результаты

```text
release-gates.md
release-gates.json
release-gates_*.zip
logs/
release-gates-consent.md
remediation/
release-confidence-gate.md
v1-release-readiness.md
```

## Классы

- `ok` — проверка полностью прошла;
- `partial_pass` — команда успешна, но важная часть пропущена;
- `infra_failed` — не готово окружение;
- `failed` — продуктовая/тестовая ошибка после выполнения prerequisites;
- `skipped_prerequisite` — запуск небезопасен или бессмыслен;
- `skipped_optional` — необязательный сигнал не запрошен;
- `planned` — только dry-run.

## Профили

| Профиль | Назначение |
|---|---|
| `diagnostic` | Без DB/runtime/download mutations |
| `prepared-local` | Разрешена подготовка dependencies/cache |
| `isolated-db` | Managed одноразовая PostgreSQL |
| `managed-runtime` | Свои backend/frontend на динамических портах |
| `full-local-release` | Максимальный локальный сигнал и clean-machine dry |

Playwright остаётся optional transition. Основным доказательством UI считается
`frontend_uiux_real_backend_core_flow` через system Chromium и managed runtime.

## Готовность

Bundle считается полезным, когда:

- все результаты классифицированы;
- секреты скрыты;
- failed/infra gates имеют `REL-*` и следующую команду;
- dry-run ничего не устанавливает и не запускает;
- DB-writing не достигает общей БД случайно;
- generated files не попадают в source archive.

