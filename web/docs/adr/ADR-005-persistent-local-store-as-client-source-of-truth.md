# ADR-005: Persistent local store как source of truth для UI клиента

- Статус: Accepted
- Дата: 2026-04-12

## Контекст

В `ADR-001` уже было принято, что проект строится как local-first система, а web-клиент должен переживать кратковременную нестабильность сети. Однако формулировка уровня "локальный cache/state на стороне клиента" недостаточна для инженерной реализации local-first data layer.

Если оставить клиент в модели "server DTO + query cache + direct render from fetch lifecycle", то:
- UI останется привязанным к online-first запросам;
- offline create/update/delete будут случайным поведением, а не системным свойством;
- будет сложно ввести pending queue и sync-ready hydration rules;
- локальный restart/reopen будет вести себя хуже, чем ожидается от local-first UX.

Нужна более точная фиксация того, что именно считается локальным источником данных для UI.

## Решение

В проекте принимается, что:
- **persistent local store** является основным источником данных для экранов клиента;
- сетевые ответы сначала нормализуются и записываются в local store;
- UI читает domain state из local store, а не напрямую из HTTP response cache;
- пользовательские мутации сначала локально коммитятся, затем попадают в pending queue;
- server выступает как источник hydration, подтверждения и синхронизации, но не как обязательный direct render source для каждого экрана.

## Что это означает practically

1. Клиент хранит normalized local records и sidecar metadata.
2. Клиент ведет pending operations queue.
3. Клиент различает local committed state и server-confirmed state.
4. Query/memory cache допустим только как производный ускоряющий слой.
5. `activity_entries` могут храниться локально как read model, но не становятся canonical sync log.
6. `me/appearance` и `board appearance` входят в ту же local-first модель, а не живут отдельно как purely online settings.

## Следствия

### Положительные
- UI перестает быть привязанным к online-first fetch lifecycle.
- Появляется системный offline/warm-start UX.
- Следующий sync этап можно строить поверх уже корректных клиентских read/write границ.
- Client-generated ids и pending operations получают понятное место в архитектуре.

### Отрицательные
- Требуется отдельный persistent storage layer на клиенте.
- Появляется дополнительная сложность normalizers, repositories и metadata.
- Придется аккуратно различать local preview state, local committed state и server-confirmed state.

## Что это не означает

Это решение не означает, что:
- full sync protocol уже определен;
- conflict resolution уже закрыт;
- backend перестает быть важным для MVP;
- любой экран обязан работать полностью offline без предварительной гидрации.

## Что это означает для следующих этапов

1. Sync model implementation plan должен использовать persistent local store и pending queue как уже принятые предпосылки.
2. Conflict resolution должен работать поверх local committed state и server-confirmed state, а не пытаться отменить local-first слой.
3. Frontend implementation должен выделить storage/repository/selector слой отдельно от transport API и отдельно от React components.
