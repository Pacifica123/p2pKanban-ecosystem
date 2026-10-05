# Побочные эффекты профилей release gates

## Классы действий

| Класс | Политика |
|---|---|
| `read-only` | Разрешено |
| `write-run-artifacts` | Разрешено в `.dev-bootstrap/runs` |
| `write-dependencies` | Нужен явный profile/flag |
| `network-download` | Нужно явное согласие |
| `write-env-files` | Согласие и backup; существующие секреты не затирать |
| `write-database` | Нужен доказанно безопасный target |
| `create-database` | Только managed DB |
| `drop-database` | Только с retention policy |
| `start-process` | Только с записью ownership |
| `stop-owned-process` | Разрешено после проверки identity |
| `stop-foreign-process` | Запрещено |
| `write-project-files` | Только через devctl patch |

## Профили

| Профиль | Разрешено | Смысл |
|---|---|---|
| `diagnostic` | Чтение и run artifacts | Только диагностика |
| `prepared-local` | Dependencies и owned processes по согласию | Частичный локальный сигнал |
| `isolated-db` | Создать/write/drop managed DB | DB/migration signal |
| `managed-runtime` | Свои backend/frontend | Runtime signal |
| `full-local-release` | Все контролируемые неразрушительные действия | Вход для beta decision |
| `clean-machine-dry` | Sandbox copy и dry checks | Portability shape |
| `clean-machine-runtime` | Изолированные deps/runtime/DB | Сильный portability signal |

## Consent summary

До выполнения должны быть понятны:

```text
profile
expanded flags
allowed/denied side effects
database target и доказательство безопасности
порты и ownership процессов
downloads/dependencies
retention policy
cleanup/rollback
```

Dry-run явно обещает отсутствие DB/dependency/network/process mutations.

## Безопасность БД

Запись разрешена только для explicit non-production `TEST_DATABASE_URL`,
managed per-run DB либо dry-run без записи. Нельзя при неудаче managed DB
молча переходить на общую dev-БД.

## Процессы

Различаются owned, foreign, stale PID, unknown port owner, crashed process и
readiness timeout. Чужой процесс не убивается ради зелёного gate.

## Граница

```text
Диагностика создаёт доказательства.
Патч изменяет проект.
```

Release gates не исправляет tracked files. Controlled mutators допустимы, если
`unsafeMutationCount == 0` и cleanup coverage успешен.

