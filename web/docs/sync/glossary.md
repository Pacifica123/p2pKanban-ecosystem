# Sync glossary

Документ фиксирует канонические sync-термины и их статус относительно MVP.

## Базовые термины

### Local-first
Клиент хранит локально рабочее состояние и может переживать сетевую
нестабильность без разрушения UX.

**Статус:** обязательная идея MVP.

### Sync-ready
Модель уже учитывает реплики, change log, tombstones, cursors и conflict policy,
даже если полный sync UX еще не является отдельной пользовательской фичей.

**Статус:** обязательная архитектурная идея MVP.

### Backend-coordinated sync
Синхронизация, в которой backend выступает координатором приема, подтверждения,
хранения и последующей доставки изменений.

**Статус:** основной sync-путь для MVP.

### Peer-to-peer sync
Прямой обмен изменениями между peer-репликами без обязательной центральной точки.

**Статус:** post-MVP / optional.

## Акторы и идентичности

### User
Пользовательская учетная запись.

### Device
Конкретное устройство или клиентская среда пользователя.

### Replica
Логический источник изменений.
В MVP обычно это browser/client context, связанный с устройством и пользователем.
Replica не следует трактовать как обязательный p2p node первого релиза.

### Coordinator
Backend-компонент, который принимает изменения, хранит прогресс и координирует
sync между клиентом и серверной моделью.

### Relay
Transport/runtime-компонент, который помогает доставке и rendezvous между сторонами, но не должен становиться canonical source of truth для merge policy или current state.

### Bootstrap
Отдельный шаг начального согласования маршрута или режима sync: coordinator endpoint, relay ticket, peer route hint, capability flags. Bootstrap не равен самому sync exchange.

### Peer discovery
Поиск возможных peer route candidates для scope или pairing-сценария. Discovery — это topology layer, а не часть доменного CRUD или merge policy.

### Transport mode
Текущий способ доставки sync envelopes: `coordinator`, `relay_assisted` или `direct_peer`. Transport mode может влиять на diagnostics/latency, но не должен менять conflict semantics.

## Единицы изменений

### Mutation
Прикладное изменение, инициированное пользователем или системой.

### ChangeEvent
Нормализованное sync-представление изменения.
Обычно содержит `event_id`, `replica_id`, `entity_type`, `entity_id`, `operation`,
`payload`, clock/time metadata.

### Field-level merge
Слияние конфликта на уровне отдельных полей, а не полной сущности.

### Reorder operation
Отдельная операция изменения порядка элементов.
Порядок нельзя надежно выводить только из `updated_at`.

## Удаление и сохранение смысла

### Delete
Удаление сущности из прикладного состояния.

### Tombstone
Sync-техническое подтверждение удаления, защищающее от "воскрешения" старой копией.

### Archive
Перевод сущности в неактивное состояние без удаления ее истории существования.
Archive не равен tombstone.

## Прогресс синхронизации

### Cursor / SyncCursor
Маркер того, до какого места одна сторона знает журнал другой стороны.

### Logical clock
Логическое упорядочивание изменений внутри replica/change stream. Используется для causal/merge semantics, а не только как transport-метка.

### Replica sequence / `replicaSeq`
Строго монотонный порядок событий внутри одной реплики. Нужен для идемпотентности, обнаружения out-of-order/gap и tie-break внутри одного replica stream.

### Server order / `serverOrder`
Глобально возрастающий порядок, назначенный coordinator/backend принятому событию. Используется для replay и cursor progress, но не всегда является semantic winner selector для same-field conflict.

### Ack
Подтверждение приема и/или продвижения курсора.

### Route hint
Подсказка от bootstrap/discovery слоя о доступном пути связи: coordinator endpoint, relay endpoint/ticket или peer signaling hint.

### Idempotency
Повторная доставка одного и того же изменения не должна ломать состояние и не
должна плодить дубли.

## Способы передачи состояния

### Incremental sync
Передача только накопившихся изменений после известного курсора.

**Статус:** желаемый основной путь.

### Snapshot
Пакетная передача состояния или крупного фрагмента состояния.

**Статус:** future-ready capability; не обязательна как пользовательская фича MVP.

### Compaction / GC
Сокращение change log и очистка старых tombstones по безопасной политике.

**Статус:** post-MVP hardening.

## Конфликты

### Conflict
Ситуация, когда несколько изменений нельзя наивно применить как один линейный поток.

### LWW per field
Выбор более нового значения для простого scalar-поля. В проекте сравнение идет не по wall-clock, а по documented conflict-key на основе `logicalClock`, `replicaSeq` и стабильных tie-break rules.

### Conflict stub
UI-visible marker, который означает, что canonical outcome уже известен, но пользователю нужно показать losing local value, review action или объяснение semantic conflict.

### Manual resolution
Ограниченный пользовательский flow для случаев, где silent auto-outcome подорвет trust: meaningful text loss, delete-vs-edit, uniqueness collision, permission/lifecycle denial.

### Reject / quarantine
Защитное отклонение или изоляция изменения, если оно нарушает права, жизненный
цикл сущности или делает merge разрушительным.
