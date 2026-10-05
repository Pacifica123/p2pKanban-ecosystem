# Sync model implementation plan v1

- Статус: Draft v1
- Дата: 2026-04-12
- Назначение: перевести уже принятые sync-термины и future-ready protocol docs в **инженерный план MVP-реализации** поверх local-first слоя.

> Этот документ опирается на `ADR-001`, `ADR-003`, `docs/sync/protocol.md`, `docs/sync/glossary.md`, `docs/architecture/local-first-data-layer-v1.md`, `docs/architecture/conflict-resolution-v1.md` и `docs/architecture/p2p-relay-bootstrap-abstraction-v1.md`. Здесь мы фиксируем **как именно реализовывать sync pipeline в MVP**, не превращая текущий этап ни в full event sourcing, ни в окончательно захарденный p2p-протокол.

> Обновление реализации, 2026-07-25: backend-coordinated sync остаётся
> каноническим, но принятые `change_events` теперь могут атомарно ставиться в
> transport outbox и асинхронно зеркалироваться в Nostr. Общие envelope,
> validation, merge order и signatures вынесены в `backend/crates/sync-core`.
> Экспериментальный Durable Object воспроизводит только coordinator-контракт
> (`dedupe`, membership, cursor, `serverOrder`, WebSocket, compact log), не
> заменяя пока основной backend. См. `ADR-006` и
> `docs/deployment/free-hosting-transports-v1.md`.

---

## 1. Что считаем целью этапа

Нужно зафиксировать практическую модель синхронизации для web-first MVP:
- какие есть sync actors;
- какие единицы синхронизации считаем каноническими;
- как выглядят outbound и inbound потоки;
- как проходит reconciliation;
- какие assumptions принимаем по batching, ordering и idempotency;
- какое sync-состояние должен видеть frontend.

Этот этап **не** включает:
- transport-specific p2p / relay / bootstrap hardening;
- финальную криптографическую или протокольную защиту;
- реализацию compaction/GC как production-hardening.

---

## 2. Главный вывод

Для MVP принимается **backend-coordinated incremental sync** как основной рабочий путь.

Итоговая формула:
- клиент локально коммитит изменения в persistent local store;
- клиент преобразует локальные mutations в outbound sync events;
- backend валидирует, дедуплицирует, упорядочивает и пишет события в `change_events`;
- backend обновляет canonical current-state таблицы и связанные проекции;
- клиент получает подтверждение push и затем подтягивает server events после cursor;
- snapshot используется как **bootstrap/recovery path**, а не как основной steady-state механизм.

Следствие:
- **incremental sync — основной режим**;
- **snapshot — fallback и cold-start инструмент**;
- frontend работает с локальным состоянием и sync status surface, а не ждет обязательный online round-trip для каждой мутации.

---

## 3. Sync actors

## 3.1. User

Владелец учетной записи и прав доступа.

## 3.2. Device

Физическое устройство или клиентская среда пользователя.

## 3.3. Replica

Логический источник изменений.

Для MVP реплика — это конкретный клиентский экземпляр, который:
- имеет `replicaId`;
- принадлежит user/device context;
- ведет собственную монотонную последовательность исходящих событий;
- хранит свой sync progress по scope.

Практически для web это обычно:
- browser profile / app install context;
- один persistent local store;
- одна активная replica registration.

## 3.4. Client sync engine

Клиентский компонент, который:
- регистрирует реплику;
- читает `pending_ops`;
- формирует outbound batches;
- отправляет push;
- вызывает pull;
- применяет inbound events в local store;
- обновляет локальные cursors и frontend-visible sync state.

## 3.5. Backend sync coordinator

Серверный слой, который:
- аутентифицирует и авторизует sync вызовы;
- регистрирует реплики;
- принимает клиентские события;
- валидирует идемпотентность и порядок;
- записывает события в `change_events`;
- назначает `serverOrder`;
- обновляет current-state tables;
- выдает incremental batches по cursor;
- при необходимости инициирует snapshot recovery path.

## 3.6. Domain projection layer

Слой серверного применения событий к текущему состоянию доменных таблиц.

Его нельзя путать:
- с `activity_entries` как user-facing history;
- с полным event sourcing как единственным стилем хранения.

---

## 4. Sync units

## 4.1. Replica registration

До полноценного push/pull клиент должен уметь:
- зарегистрировать `replicaId`;
- обновить metadata реплики (`device`, `platform`, `appVersion`, `protocolVersion`);
- получить server-side acknowledgment, что эта реплика допустима к sync.

## 4.2. Sync scope

В MVP принимаются два типа scope:
- `global`
- `workspace`

### `global`

Используется для данных, которые не принадлежат одной конкретной доске/воркспейсу или нужны на верхнем уровне приложения:
- список workspaces пользователя;
- `me/appearance`;
- lightweight sync health / replica state.

### `workspace`

Используется для данных, которые естественно синхронизируются внутри рабочего пространства:
- boards;
- columns;
- cards;
- board appearance;
- позже labels/checklists/comments.

Практическое правило:
- клиент хранит отдельный cursor per scope;
- один workspace не обязан блокировать sync другого workspace;
- при открытии board screen клиент активирует workspace sync context.

## 4.3. Pending operation

Локальная прикладная запись намерения пользователя (`pending_ops`).

Это **еще не канонический server event**. Pending op существует на стороне клиента, чтобы:
- пережить reload/offline;
- коалесцировать локальные изменения;
- отправить их позже в sync pipeline.

## 4.4. Outbound sync event

Нормализованная форма изменения, которую клиент отдает на push.

Минимальный набор полей для реализации v1:
- `eventId`
- `replicaId`
- `replicaSeq`
- `logicalClock`
- `workspaceId` (nullable для global scope)
- `entityType`
- `entityId`
- `operation`
- `fieldMask`
- `payload`
- `occurredAt`
- `baseServerOrder` или эквивалентный baseline marker (optional)
- `metadata`

### Почему нужны и `replicaSeq`, и `logicalClock`

Они решают разные задачи:
- `replicaSeq` — строгий монотонный порядок **внутри одной реплики** и надежная идемпотентность;
- `logicalClock` — causal/merge metadata, которая помогает в conflict handling и сравнении изменений.

Нормативная граница для реализации v1:
- `serverOrder` используется для replay и pull cursor;
- `logicalClock` + `replicaSeq` участвуют в same-field/structural winner selection согласно `docs/architecture/conflict-resolution-v1.md`;
- нельзя подменять conflict policy простым правилом "кто позже записался на сервер, тот и прав".

### Важное инженерное уточнение

Текущая БД уже готова к этому различию:
- `change_events.replica_seq`
- `change_events.lamport`

Поэтому для реализации `replicaSeq` должен считаться **обязательным полем push-модели**, даже если в части ранних draft-contracts он еще не прописан явно.

## 4.5. Accepted server event

После серверной валидации исходящее событие превращается в server-side accepted event:
- сохраняется в `change_events`;
- получает `serverOrder`;
- получает `receivedAt`/`appliedAt`;
- участвует в pull-выдаче другим репликам и при необходимости этой же реплике.

## 4.6. Sync cursor

Маркер прогресса чтения server event stream.

Для MVP canonical cursor для incremental pull:
- `scope`
- `replicaId`
- `lastServerOrder`
- опционально `lastEventId`

Курсор продвигается только после **долговечного локального применения** inbound batch.

## 4.7. Tombstone

Удаление синхронизируется как отдельный факт, а не как мгновенное физическое исчезновение.

Сервер обязан:
- фиксировать tombstone при удалении sync-visible сущности;
- не допускать resurrection устаревшими данными;
- отдавать этот факт через incremental sync.

## 4.8. Snapshot

Пакетное представление состояния scope на некоторый момент времени.

В MVP snapshot нужен не как основной UX-сценарий, а как recovery path для:
- cold bootstrap пустой реплики;
- очень большого отставания по cursor;
- cursor reset;
- будущего import/export/backup.

---

## 5. Каноническая модель потоков

В MVP есть два главных потока:

### A. Outbound

`local mutation -> pending_ops -> push batch -> server apply -> ack`

### B. Inbound

`known cursor -> pull -> inbound events -> local apply -> cursor advance`

Они связаны, но не обязаны исполняться одним монолитным циклом. Клиентский engine может:
- независимо триггерить push при локальных изменениях;
- независимо триггерить pull по timer/focus/reconnect/manual refresh.

---

## 6. Outbound flow

## 6.1. Local commit

Пользователь инициирует мутацию.

Клиент в одной локальной транзакции:
- изменяет domain records в local store;
- обновляет `entity_meta`;
- создает или коалесцирует `pending_ops`;
- повышает local `replicaSeq` и `logicalClock` для нужных операций;
- помечает UI как `Saved locally` / `Changes pending`.

Это продолжает правила local-first слоя: сначала локальный commit, потом сеть.

## 6.2. Batch assembly

Sync engine выбирает готовые к отправке pending ops и формирует batch по правилам:
- один batch относится к одному scope;
- внутри batch события отсортированы по `replicaSeq`;
- batch ограничен по размеру и количеству событий;
- коалесцируемые updates сжимаются до отправки, если это не ломает пользовательскую семантику.

Рекомендуемые стартовые лимиты v1:
- до `100` событий на один push batch;
- до `256 KB - 512 KB` полезной нагрузки на batch;
- крупные reorder/move пачки дополнительно режутся по scope.

Это не финальные числа hardening-этапа, а инженерный старт для реализации.

## 6.3. Push request

Клиент вызывает `/sync/push` с:
- `replicaId`;
- `scope`/`workspaceId`;
- отсортированным набором events;
- опционально metadata о клиентской версии и last known cursor.

## 6.4. Server validation

Backend sync coordinator выполняет по каждому событию минимум:
- проверку auth/session/ownership;
- проверку, что `replicaId` допустим для текущего пользователя;
- проверку shape и semantic validation payload;
- проверку идемпотентности по `eventId` и/или `(replicaId, replicaSeq)`;
- проверку того, что нет грубого нарушения causal/order assumptions;
- проверку permission/business rules на уровне домена.

## 6.5. Server apply

Для принятого события сервер:
1. пишет запись в `change_events`;
2. назначает `serverOrder`;
3. при необходимости создает/обновляет `tombstones`;
4. обновляет current-state таблицы;
5. обновляет audit/activity projections там, где это уже есть;
6. формирует per-event result.

## 6.6. Push acknowledgment

На каждое событие клиент должен получить статус:
- `accepted`
- `duplicate`
- `rejected`
- `conflict`

Для `accepted`/`duplicate` желательно вернуть:
- `eventId`
- `serverOrder`
- `appliedAt` или эквивалентный ack marker

## 6.7. Local finalize after push

После ответа `/sync/push` клиент:
- снимает pending с принятых событий;
- оставляет `duplicate` как завершенный no-op;
- переводит `rejected/conflict` в user-visible failure state;
- сохраняет server ack metadata в local store;
- не продвигает pull cursor только на основании push ack.

Это важная граница:
- push ack подтверждает принятие сервером конкретной мутации;
- pull cursor подтверждает, что клиент уже **локально применил входящий server stream**.

---

## 7. Inbound flow

## 7.1. Pull trigger

Pull запускается:
- после старта приложения;
- после успешной replica registration;
- после reconnect;
- после успешного push;
- по таймеру/heartbeat;
- по ручному refresh.

## 7.2. Pull request

Клиент вызывает `/sync/pull` для конкретного scope и передает:
- `replicaId`;
- текущий cursor scope;
- `limit`;
- optional filters, если они появятся позже.

## 7.3. Server read from event log

Сервер выбирает события после `lastServerOrder`:
- в нужном scope;
- в порядке возрастания `serverOrder`;
- с учетом permission boundaries;
- с возможностью пагинации `hasMore`.

## 7.4. Client inbound apply

Клиент применяет события в local store **строго по возрастанию `serverOrder`**.

На этом этапе делаются:
- upsert / patch domain records;
- локальная обработка tombstones;
- снятие stale markers;
- reconciliation с локальными pending/failure markers;
- обновление local projections, если они завязаны на эти сущности.

## 7.5. Cursor advance

Только после успешного durable apply всего inbound batch клиент:
- обновляет `lastServerOrder` в `sync_state`;
- сохраняет `lastSuccessfulPullAt`;
- уменьшает perceived lag.

Если batch не применился целиком:
- cursor не продвигается;
- следующий pull может безопасно получить эти же события повторно;
- apply logic обязана быть идемпотентной.

---

## 8. Reconciliation stages

Под reconciliation в этом проекте понимаем не абстрактный merge "все со всем", а конкретную поэтапную обработку пересечения локальных и входящих изменений.

## 8.1. Stage 1 — local mutation staging

Локальное состояние уже изменено, но server confirmation еще нет.

Источник истины для UI в этот момент:
- local store;
- `entity_meta`;
- `pending_ops`.

## 8.2. Stage 2 — push acknowledgment reconciliation

Клиент сопоставляет ack с локальными pending ops:
- `accepted` -> pending снимается;
- `duplicate` -> pending снимается как already known;
- `rejected/conflict` -> pending становится failure state.

## 8.3. Stage 3 — inbound stream reconciliation

Когда клиент получает server events, он должен уметь:
- распознавать, что часть событий относится к его же прошлым мутациям;
- не дублировать уже локально примененную бизнес-операцию;
- нормализовать `entity_meta` и `dirtyFields`;
- сохранить более полный server-side canonical state.

## 8.4. Stage 4 — conflict/failure stub creation

Если автоматический merge не разрешает ситуацию безопасно, клиент не пытается "магически" скрыть проблему.

Он делает одно из двух:
- переводит операцию в `failed` / `retryable`;
- создает `conflict_stub` или эквивалентный UI-visible marker.

Полная conflict matrix, manual-resolution policy и UX surface теперь вынесены в `docs/architecture/conflict-resolution-v1.md`. Здесь мы фиксируем только место этих исходов в pipeline.

## 8.5. Stage 5 — compaction-ready normalization

После успешной синхронизации локальная модель должна быть приведена к виду, в котором позже возможны:
- queue cleanup;
- entity_meta cleanup;
- будущая compaction/GC стратегия.

---

## 9. Ordering assumptions

## 9.1. Что гарантируем

В MVP принимаем следующие гарантии:
- внутри одной реплики исходящие события имеют строгий порядок по `replicaSeq`;
- сервер назначает глобально возрастающий `serverOrder`;
- pull внутри одного scope возвращает события по возрастанию `serverOrder`;
- клиент применяет inbound batch в этом же порядке.

## 9.2. Что не гарантируем

Не гарантируется:
- единый causally perfect мировой порядок между всеми репликами;
- отсутствие race-condition между почти одновременными событиями разных реплик;
- отсутствие дубликатов доставки.

Поэтому корректность строится не на "идеальной сети", а на:
- идемпотентности;
- cursor-based incremental pull;
- documented conflict policy;
- deterministic apply order.

---

## 10. Idempotency assumptions

## 10.1. На push

Сервер считает событие дубликатом, если уже видел:
- тот же `eventId`, либо
- ту же пару `(replicaId, replicaSeq)`.

Это дает защиту и от повторной отправки одного payload, и от клиента, который после reload/retry отправил тот же логический event повторно.

## 10.2. На pull/apply

Клиент обязан быть готов к повторной доставке одного и того же server event, если:
- cursor еще не был продвинут;
- pull повторен после сбоя;
- reconnect произошел посередине apply.

Следовательно inbound apply должен быть безопасным при повторе.

## 10.3. Для UI

Пользователь не должен видеть удвоение карточек/колонок/действий из-за повторной доставки одного и того же event.

---

## 11. Batching assumptions

## 11.1. Push batching

Batching делается по следующим правилам:
- не смешиваем `global` и `workspace` scope в одном batch;
- не отправляем события в произвольном порядке;
- не откладываем push бесконечно ради идеальной коалесценции;
- при большом числе pending ops предпочитаем несколько коротких batch вместо одного огромного.

## 11.2. Pull batching

Pull делает серверно-упорядоченную пагинацию:
- `limit` обязателен;
- `hasMore` обязателен;
- клиент может крутить цикл pull-until-caught-up, пока scope не догонит сервер.

## 11.3. Reorder batching

`reorder` нельзя превращать в хаотический поток множества мелких PATCH, если можно выразить операцию компактнее.

Для MVP допустимы два пути:
- one event per moved entity with clear target position;
- compact reorder payload for a group.

Но нужно выбрать один канонический wire-shape на этапе реализации API, а не поддерживать несколько несогласованных вариантов.

---

## 12. Snapshot vs incremental sync

## 12.1. Что считаем основным режимом

Основной рабочий режим MVP — **incremental sync after known cursor**.

Он нужен для:
- steady-state синхронизации;
- низкой стоимости повторных обновлений;
- хорошего поведения при частых небольших изменениях;
- фона, который естественно сочетается с local-first UX.

## 12.2. Когда нужен snapshot

Snapshot нужен как fallback/recovery path, если:
- реплика новая и cursor еще не seeded;
- локальный store пуст и нужно быстро получить исходное состояние scope;
- сервер выполнил compaction, и старый cursor больше не покрывается incremental history;
- отставание слишком велико и incremental pull неэффективен;
- делается backup/restore/import scenario.

## 12.3. Как snapshot должен выглядеть в MVP

Для MVP не требуется полноценный chunked snapshot transport как пользовательская фича.

Принимаем более прагматичный план:
- **cold bootstrap может использовать scope snapshot через обычный HTTP state-read**;
- отдельный `snapshot_manifest` и chunking остаются future-ready capability;
- после snapshot клиент получает seeded cursor и дальше переключается на incremental pull.

Иначе говоря:
- bootstrap может быть "получи текущее состояние workspace";
- steady-state должен быть именно incremental.

## 12.4. Когда клиент должен запросить snapshot-recovery

Frontend sync engine переводит scope в `needs_snapshot`, если:
- сервер вернул `cursor_expired` / `snapshot_required`;
- локальный cursor поврежден;
- локальный store был очищен, а pending-состояние уже не восстанавливается корректно;
- разрыв между локальным cursor и сервером превысил допустимый operational threshold.

---

## 13. Server responsibilities

Сервер обязан:
- быть координатором sync для MVP;
- хранить реестр `replicas`;
- принимать и валидировать outbound events;
- обеспечивать идемпотентность push;
- назначать `serverOrder`;
- хранить `change_events` и `tombstones`;
- уметь читать incremental stream по cursor;
- обновлять current-state tables;
- не смешивать user-facing `activity_entries` с canonical sync log;
- выдавать sync health/status и нужные recovery signals;
- на следующем этапе уметь выступать bootstrap source для route hints, не смешивая это с canonical merge/apply logic.

Сервер **не обязан** на этом этапе:
- реализовывать peer discovery;
- давать full mesh p2p transport;
- решать все конфликты красивым авто-merge для любого доменного кейса;
- внедрять compaction/GC как завершенную подсистему.

---

## 14. Client responsibilities

Клиент обязан:
- иметь persistent local store как основной read/write слой;
- генерировать client IDs и replica-local sequence;
- вести `pending_ops` и локальные metadata;
- регистрировать реплику;
- выполнять push/pull независимо от UI рендера;
- держать per-scope cursors;
- применять inbound events детерминированно;
- продвигать cursor только после durable apply;
- показывать frontend-visible sync state;
- не путать sync failures с отсутствием локальных данных;
- держать transport/backend details за отдельным adapter boundary.

Клиент **не обязан** на этом этапе:
- поддерживать несколько transport backends;
- хранить полную cross-device conflict matrix в UI;
- отображать внутренний протокольный шум пользователю как низкоуровневые ошибки.

---

## 15. Event lifecycle

### 1. Create locally
Клиент создает локальную domain mutation и pending op.

### 2. Normalize to outbound event
Pending op превращается в push-ready event с `replicaSeq` и `logicalClock`.

### 3. Push to backend
Событие отправляется через текущий coordinator transport path (в MVP это `/sync/push`).

### 4. Validate and dedupe
Сервер проверяет права, shape, порядок, дубликаты.

### 5. Persist in `change_events`
Событие получает server-side запись и `serverOrder`.

### 6. Apply to current state
Сервер обновляет доменную проекцию и tombstones при необходимости.

### 7. Ack to source replica
Исходная реплика получает per-event result.

### 8. Pull by replicas
Событие попадает в incremental stream и читается по cursor.

### 9. Apply in local stores
Клиенты применяют событие к локальным сущностям и метаданным.

### 10. Cursor advance
После durable apply scope cursor двигается вперед.

### 11. Later hardening
Позже событие может участвовать в compaction, backup, snapshot, audit correlation и transport-level route evolution без изменения своей sync-семантики.

---

## 16. Frontend-visible sync surface

Frontend должен видеть не сырой transport dump, а нормализованное состояние sync engine.

Минимально обязательные surface-сигналы:
- online / offline / degraded;
- replica ready / registering / revoked;
- idle / syncing / pushing / pulling / reconciling / backoff / needs_snapshot;
- pending count;
- failed count;
- last successful sync timestamps;
- per-scope hydration/sync health;
- per-entity `synced / pending / failed / conflict_stub` markers.

Подробная модель вынесена в `frontend-visible-sync-state-model-v1.md`.

---

## 17. Implementation sequence

## Phase 0 — contract alignment

Перед кодом нужно синхронизировать контракты:
- подтвердить wire-shape `ClientChangeEvent`;
- явно добавить `replicaSeq` в sync contract;
- договориться о canonical `scope` shape;
- подтвердить error codes `duplicate`, `conflict`, `snapshot_required`, `cursor_expired`.

## Phase 1 — replica and status foundation

Сделать рабочими:
- `POST /sync/replicas`
- `GET /sync/status`

На выходе клиент должен уметь:
- завести реплику;
- получить sync health;
- хранить replica metadata локально.

## Phase 2 — outbound pipeline

Сделать рабочими:
- local pending queue -> outbound event normalization;
- `POST /sync/push`;
- идемпотентное принятие `change_events`;
- базовый ack flow.

Это первый usable sync slice для local-first мутаций.

## Phase 3 — incremental pull

Сделать рабочими:
- per-scope cursor storage;
- `POST /sync/pull`;
- inbound apply по `serverOrder`;
- cursor advance после durable apply.

После этого sync становится двусторонним.

## Phase 4 — reconciliation hardening

Добавить:
- аккуратную обработку rejected/conflict результатов;
- sync status surface для frontend;
- retry/backoff;
- recovery markers `needs_snapshot`.

## Phase 5 — snapshot recovery path

Добавить:
- seed/reset cursor через snapshot bootstrap;
- серверный сигнал `snapshot_required`;
- безопасное переинициализирование scope без смешивания со старыми курсорами.

## Phase 6 — post-MVP hardening

Отдельно потом:
- compaction/GC;
- расширенная conflict policy;
- relay/p2p transport через отдельный transport abstraction layer;
- chunked snapshot exchange;
- protocol hardening/security refinements.

---

## 18. Что важно не перепутать

### 1. `pending_ops` != `change_events`

`pending_ops` — локальная очередь намерений клиента.
`change_events` — серверный канонический журнал принятых sync-событий.

### 2. `activity_entries` != sync log

Activity — пользовательская read model.
Она не должна становиться источником истины для sync.

### 3. Push ack != cursor advance

Ack подтверждает прием мутации сервером.
Cursor подтверждает локальное применение server stream.

### 4. Snapshot != основной режим

Основной режим — incremental.
Snapshot нужен для bootstrap/recovery.

### 5. Local-first не отменяет server coordination

В MVP клиент локально коммитит изменения, но server остается coordinator'ом:
- для permissions;
- для dedupe;
- для глобального `serverOrder`;
- для доставки событий другим репликам.

---

## 19. Короткий итог

Для проекта принимается следующая MVP-модель:
- **реплика-ориентированный incremental sync** поверх local-first клиента;
- **server-coordinated event acceptance** через `change_events` и `serverOrder`;
- **per-scope cursors** для `global` и `workspace` потоков;
- **snapshot как recovery/bootstrap path**, а не как основной steady-state transport;
- **frontend-visible sync state** как обязательная часть UX, а не скрытая внутренняя механика.
