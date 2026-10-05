# Политика разрешения конфликтов

Этот документ фиксирует **канонические правила**, а подробная матрица, примеры и UX-policy раскрыты в `docs/architecture/conflict-resolution-v1.md`.

## Общий принцип

В проекте запрещен неявный conflict-management "по удаче". Для каждого класса данных должна существовать явная стратегия:
- `LWW per field`;
- merge by field;
- structural merge;
- reject/quarantine;
- manual resolution surface.

Важно: для реальной реализации конфликтов и идемпотентности нужны **оба** поля:
- `replicaSeq` — порядок внутри реплики;
- `logicalClock` — causal/merge ordering.

`serverOrder` нужен для event-stream replay и cursor progress, но не подменяет semantic winner selection для одного и того же поля.

## Базовые стратегии

### 1. Last-Write-Wins per field
Используется для:
- простых scalar-полей;
- short text;
- enum/flag/date values;
- low-stakes appearance settings.

Сравнение идет по conflict-key:
1. `logicalClock`
2. `replicaSeq` внутри той же реплики
3. `replicaId`
4. `eventId`

### 2. Merge by field
Используется, когда разные реплики изменили разные поля одной сущности.

Пример:
- `card.title` и `card.dueAt`;
- `board.name` и `board.description`.

### 3. Structural operation merge
Используется для:
- reorder колонок;
- move/reorder карточек;
- reorder checklist items.

Порядок нельзя надежно восстанавливать только по `updated_at`, поэтому reorder/move считается отдельной операцией.

### 4. Membership/set merge
Используется для:
- add/remove labels;
- add/remove checklist items;
- add/remove membership edges.

`add/add` и `remove/remove` идемпотентны. `add/remove` той же связи разрешается по policy membership winner, но lifecycle guards по parent/delete остаются сильнее.

### 5. Reject or manual resolution
Используется там, где автоматическое слияние разрушает смысл или trust.

Примеры:
- delete vs meaningful local edit;
- parent deleted / archived;
- permission loss;
- uniqueness collision;
- high-value text loss.

## Приоритет lifecycle и tombstone

Tombstone и lifecycle guards имеют приоритет над stale update, если только:
- не существует отдельной валидной операции `restore`;
- не пройдены права и инварианты для восстановления.

Следствия:
- delete по умолчанию выигрывает у stale edit;
- archive/revoke/policy denial не маскируются под обычный merge;
- implicit resurrection запрещен.

## Особые случаи

### Ordered structures
Порядок колонок, карточек и checklist items нельзя выводить только из `updated_at`. Нужны отдельные reorder-операции и позиционные поля.

### High-value text
Для `card.description`, `comment.body` и других содержательных текстовых полей допустим canonical auto-outcome, но проигравший локальный текст должен сохраняться в `conflict_stub`, если его потеря заметна пользователю.

### Comments
Для comments допускается:
- concurrent create -> append обеих записей;
- `comment.body` -> `LWW per field`;
- delete vs edit -> delete wins canonically + review/copy surface.

### Read models
`activity_entries` и `audit_log` не являются источником разрешения конфликтов. Они отражают исход canonical операций, но не выбирают winner.

## Технические требования

1. Решение конфликтов должно быть детерминированным.
2. Повторное применение одинакового набора событий должно давать тот же результат.
3. Duplicate/replay не должен показываться пользователю как обычный conflict.
4. Conflict policy должна тестироваться отдельно от HTTP-хендлеров.
5. В MVP допустимо отсутствие отдельного conflict center, но не допустимо скрывать meaningful loss без user-visible surface.
