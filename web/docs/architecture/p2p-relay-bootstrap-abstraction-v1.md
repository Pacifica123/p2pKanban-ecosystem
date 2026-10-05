# P2P / relay / bootstrap abstraction v1

- Статус: Draft v1
- Дата: 2026-04-12
- Назначение: отделить transport/topology слой от UI, local-first data layer и общей sync-модели, чтобы optional p2p развивался как **надстраиваемый transport path**, а не как магия внутри экранов или CRUD.

> Этот документ продолжает `ADR-001`, `ADR-003`, `docs/sync/protocol.md`, `docs/architecture/local-first-data-layer-v1.md` и `docs/architecture/sync-model-implementation-plan-v1.md`. Здесь фиксируется не конечный wire protocol и не deployment-специфика, а **граница между sync engine и transport layer**: discovery, bootstrap, relay, topology assumptions и phased rollout.

> Обновление реализации, 2026-07-25: транспортная граница получила первые
> серверные адаптеры. `backend/crates/sync-core` теперь содержит независимые от
> Axum/sqlx envelope, validation, merge order и HMAC signatures;
> `nostr-transport` реализует зашифрованное shadow-зеркало, а
> `iroh-transport` — прямой QUIC-канал. Основным рабочим путём по-прежнему
> остаётся backend coordinator. Актуальный rollout и эксплуатационные
> ограничения описаны в `ADR-006` и
> `docs/deployment/free-hosting-transports-v1.md`.

---

## 1. Что считаем целью этапа

Нужно зафиксировать архитектуру, в которой:
- sync semantics остается одной и той же независимо от того, идет обмен через coordinator, relay или direct peer channel;
- peer discovery не протекает в UI и не зашивается в доменные сервисы;
- relay рассматривается как отдельная operational role, а не как скрытый "умный сервер";
- bootstrap — это отдельный этап установления пути связи, а не часть merge policy;
- frontend app logic зависит от `SyncEngine`, а не от WebRTC/WebSocket/NAT-деталей.

Этот этап **не** включает:
- финальный threat model и криптографический hardening;
- конкретный cloud/self-host deployment blueprint;
- детальный UI flow discovery/connection management;
- замену текущего backend-coordinated sync в MVP.

---

## 2. Главный вывод

Для проекта принимается следующая иерархия:

1. **Domain + sync semantics** живут выше транспорта.
2. **Sync engine** знает про `replica`, `cursor`, `change event`, `ack`, `snapshot_required`, `conflict_notice`.
3. **Transport abstraction** знает, как доставить envelope между участниками.
4. **Topology services** знают, как найти/согласовать путь: coordinator lookup, bootstrap ticket, relay rendezvous, peer candidate selection.
5. **Concrete transport backends** знают детали HTTP / WebSocket / WebRTC / relay channel.

Следствие:
- `LWW`, `replicaSeq`, `serverOrder`, conflict policy и cursor semantics **не должны зависеть от transport mode**;
- relay не должен подменять coordinator semantics;
- direct peer transport может добавляться позже без переписывания UI и local-first слоя.

---

## 3. Канонические слои

```text
UI / feature screens
  -> selectors / view-models
  -> local-first repositories + persistent local store
  -> sync engine
  -> transport abstraction
  -> topology services (bootstrap / discovery / route selection)
  -> transport backend
  -> remote coordinator / relay / peer
```

### Что важно по слоям

#### UI / feature screens
Экран не знает о NAT traversal, SDP, relay tickets, peer candidates и transport retries.
Экран видит только:
- sync state surface;
- user actions `retry`, `refresh`, `resolve conflict`, `connect later`;
- optionally диагностический `transportMode`, если это реально полезно.

#### Local-first layer
Local-first слой не зависит от способа доставки. Он хранит:
- локальные сущности;
- `pending_ops`;
- cursors;
- per-entity sync metadata.

#### Sync engine
Sync engine — единственное место, где транспорт встречается с sync semantics.
Он:
- формирует outbound envelopes;
- принимает inbound envelopes;
- ведет reconciliation;
- выбирает snapshot recovery;
- обновляет frontend-visible sync state.

#### Transport abstraction
Transport abstraction не решает конфликтов и не читает доменные таблицы.
Его задача:
- открыть/поддерживать канал;
- передать envelope;
- вернуть transport-level delivery result;
- сигнализировать `connected / disconnected / degraded`.

#### Topology services
Отвечают на вопрос **"куда и как подключаться"**, но не на вопрос **"как merge-ить события"**.

---

## 4. Ключевые роли и их границы

## 4.1. Coordinator

Coordinator — это авторитетный для MVP backend-компонент, который:
- регистрирует реплики;
- валидирует и принимает изменения;
- назначает `serverOrder`;
- хранит `change_events`, `tombstones`, cursors и recovery signals.

Coordinator:
- **может** быть bootstrap source;
- **может** быть fallback transport endpoint;
- **не обязан** быть relay.

## 4.2. Relay

Relay — transport/runtime-компонент, который помогает трафику пройти между сторонами, когда direct path невозможен, нестабилен или operationally неудобен.

Relay:
- forward'ит envelopes или transport frames;
- может быть rendezvous point;
- может аутентифицировать соединение и проверять scope-bound tickets;
- может rate-limit / meter / expire sessions.

Relay **не должен**:
- назначать `serverOrder`;
- решать conflict policy за sync engine;
- менять доменный payload;
- становиться неявным источником истины для current state.

## 4.3. Bootstrap service

Bootstrap service отвечает за начальное согласование пути связи. Он может:
- выдать endpoint hint;
- выдать relay ticket;
- выдать peer candidate list;
- вернуть режим `coordinator_only` как безопасный fallback.

Bootstrap service **не обязан** быть отдельным процессом. На ранних этапах его роль может играть coordinator.

## 4.4. Discovery service

Discovery service решает задачу **поиска возможных peer route candidates**.

Он может использовать:
- membership context workspace;
- known devices/replicas пользователя;
- invitation/share code;
- relay rendezvous registry.

Discovery service **не должен** напрямую диктовать UI, как рисовать экраны, и **не должен** становиться частью доменных CRUD handler'ов.

## 4.5. Peer

Peer — другая replica или device endpoint, которая способна:
- пройти auth/capability negotiation;
- принять/pередать sync envelopes;
- подтвердить scope access;
- поддерживать keepalive/liveness для transport session.

Peer не обязан быть always-online и не должен предполагаться доступным по стабильному IP.

---

## 5. Transport boundaries

## 5.1. Что transport layer имеет право знать

Transport layer имеет право знать:
- `replicaId`;
- protocol version / capability flags;
- target scope(s);
- envelope type;
- session / ticket / auth metadata;
- route hints и liveness state.

## 5.2. Что transport layer не должен знать как business-логику

Transport layer не должен решать:
- кто выиграл `same_field` conflict;
- как merge-ить reorder;
- как строится `activity_entries`;
- как выглядит current board/card projection;
- как показывать ошибки на экране.

## 5.3. Что sync engine ожидает от transport layer

Sync engine ожидает:
- доставку envelope по выбранному маршруту;
- сигнал `delivered / not_delivered / transport_retryable / transport_blocked`;
- transport diagnostics;
- события изменения канала (`connected`, `reconnecting`, `closed`).

## 5.4. Что UI имеет право знать

UI имеет право знать только:
- можно ли сейчас синхронизироваться;
- есть ли pending changes;
- нужен ли user action;
- optional: какой сейчас режим — `coordinator`, `relay_assisted`, `direct_peer`.

UI **не должен** зависеть от:
- SDP/ICE/WebRTC signaling;
- discovery query shape;
- relay routing internals;
- количества peer candidates.

---

## 6. Канонический transport contract

Ниже — минимальная абстракция, которую должен видеть sync engine.

```ts
export type TransportMode = 'coordinator' | 'relay_assisted' | 'direct_peer';
export type DeliveryResult =
  | { kind: 'delivered'; remoteAckExpected: boolean }
  | { kind: 'duplicate_delivery' }
  | { kind: 'retryable_transport_error'; code: string }
  | { kind: 'blocked_transport_error'; code: string };

export interface SyncEnvelope {
  protocolVersion: string;
  scope: { type: 'global' | 'workspace'; id: string | null };
  envelopeType:
    | 'hello'
    | 'push_events'
    | 'pull_request'
    | 'ack'
    | 'snapshot_request'
    | 'snapshot_offer'
    | 'conflict_notice';
  sourceReplicaId: string;
  targetReplicaId?: string | null;
  payload: unknown;
}

export interface TransportSessionState {
  mode: TransportMode;
  connectivity: 'disconnected' | 'connecting' | 'connected' | 'degraded';
  routeKind: 'coordinator' | 'relay' | 'peer';
  lastTransportErrorCode: string | null;
}

export interface SyncTransport {
  open(): Promise<void>;
  close(): Promise<void>;
  getState(): TransportSessionState;
  send(envelope: SyncEnvelope): Promise<DeliveryResult>;
  subscribe(handler: (envelope: SyncEnvelope) => void): () => void;
  subscribeState(handler: (state: TransportSessionState) => void): () => void;
}
```

### Смысл этого контракта

- `SyncTransport` не знает про local tables.
- `SyncTransport` не возвращает доменный merge result.
- `SyncTransport` не обязан гарантировать canonical apply.
- final `ack/conflict_notice/snapshot_required` остаются sync-semantics сообщениями, а не transport-исключениями.

---

## 7. Bootstrap и discovery abstraction

## 7.1. Почему это отдельный слой

Discovery и bootstrap не должны смешиваться с transport open/send, потому что это разные задачи:
- discovery отвечает на вопрос **кого и где искать**;
- bootstrap отвечает на вопрос **как стартовать маршрут/сессию**;
- transport отвечает на вопрос **как уже передавать envelopes**.

## 7.2. Минимальный bootstrap contract

```ts
export type RouteHint =
  | { kind: 'coordinator'; endpoint: string }
  | { kind: 'relay'; endpoint: string; relayTicket: string }
  | { kind: 'peer'; peerReplicaId: string; signalingToken: string };

export interface BootstrapResult {
  preferredMode: TransportMode;
  routeHints: RouteHint[];
  expiresAt: string | null;
  fallbackAllowed: boolean;
}

export interface SyncBootstrapService {
  bootstrap(scope: { type: 'global' | 'workspace'; id: string | null }): Promise<BootstrapResult>;
}
```

## 7.3. Минимальный discovery contract

```ts
export interface PeerCandidate {
  replicaId: string;
  userId?: string | null;
  routeKinds: Array<'relay' | 'direct_peer'>;
  lastSeenAt: string | null;
  scopes: Array<{ type: 'workspace'; id: string }>;
}

export interface PeerDiscoveryService {
  discover(scope: { type: 'workspace'; id: string }): Promise<PeerCandidate[]>;
}
```

### Что это дает

- можно сначала иметь only `coordinator` bootstrap result;
- затем добавить relay hints, не меняя sync engine contract;
- потом добавить peer candidates как post-MVP capability;
- UI не трогает transport детали, пока не нужен отдельный connection-management screen.

---

## 8. Bootstrap mechanisms

Допускаются следующие bootstrap-механизмы, но не все обязательны одновременно.

### A. Static coordinator bootstrap
Самый простой путь MVP:
- клиент знает coordinator endpoint из config;
- replica регистрируется через coordinator;
- sync идет только через backend.

### B. Session-bound bootstrap
После login coordinator выдает bootstrap response с route hints:
- coordinator endpoint;
- optional relay endpoint;
- capability flags.

### C. Workspace invitation bootstrap
При входе по invite/space join link bootstrap может вернуть:
- scope-bound ticket;
- список допустимых relay routes;
- политику fallback в coordinator mode.

### D. Manual/QR/bootstrap code
Для future device-pairing сценариев возможен bootstrap через:
- код;
- QR;
- одноразовый pairing token.

### E. Cached bootstrap reuse
Клиент может краткосрочно переиспользовать недавний bootstrap result, если:
- ticket не истек;
- scope access не отозван;
- transport diagnostics не показывают постоянную блокировку.

---

## 9. Relay-compatible design rules

### 1. Relay не переписывает sync semantics
`ack`, `conflict_notice`, `snapshot_required`, cursor semantics и envelope types остаются теми же.

### 2. Relay — не hidden database
Relay не становится permanent source of truth и не подменяет `change_events`/current state таблицы.

### 3. Relay допускается как fallback
Если direct peer канал не поднялся, sync engine должен уметь безопасно откатиться в `relay_assisted` или `coordinator` mode.

### 4. Relay может быть opaque или semi-aware
На ранних фазах relay может знать только ticket/session metadata и не трогать payload. Более "умный" relay допустим лишь operationally, но не как semantic owner конфликтов.

### 5. Relay должен быть scope-aware
Relay ticket и route binding должны быть ограничены scope/user/session, чтобы нельзя было использовать один и тот же маршрут для произвольного доступа.

### 6. Relay должен быть disposable
Потеря relay не должна уничтожать local-first данные; это деградация transport path, а не потеря рабочей модели клиента.

---

## 10. Online topology assumptions

## 10.1. Что считаем реальностью

Нельзя предполагать:
- что оба peer'а online одновременно всегда;
- что у клиента есть стабильный публичный адрес;
- что browser environment позволит прямое соединение без signaling/relay;
- что background execution и keepalive одинаково работают на всех платформах.

## 10.2. Базовые допустимые топологии

### `coordinator_only`
Весь sync идет через backend. Это baseline MVP.

### `relay_assisted_client_to_service`
Клиент использует relay/rendezvous как transport helper, но canonical coordinator semantics остается на backend.

### `relay_assisted_peer`
Peer'ы обмениваются envelopes через relay path, когда direct route недоступен.

### `direct_peer_with_bootstrap`
Bootstrap/discovery помогает peer'ам найти друг друга, после чего transport идет напрямую.

### `mixed`
Для разных scope/devices одновременно могут использоваться разные режимы, но sync engine должен нормализовать это в одну surface-модель.

## 10.3. Что не обещаем

На этом этапе не обещается:
- full mesh между всеми устройствами;
- always-on peer presence;
- transparent LAN/WAN discovery без explicit bootstrap;
- одинаковая latency/throughput семантика для всех transport modes.

---

## 11. Integration contracts with sync layer

## 11.1. Sync layer -> transport

Sync layer должен уметь передать:
- `hello`/capabilities;
- `push_events`;
- `pull_request`;
- `ack`;
- `snapshot_request` / `snapshot_offer`;
- `conflict_notice`.

## 11.2. Transport -> sync layer

Transport должен уметь вернуть:
- inbound envelope;
- transport session state;
- retryable transport failure;
- blocked transport failure;
- route switch notification.

## 11.3. Coordinator-specific logic не должна течь вверх

Даже если сегодня `push` и `pull` идут через HTTP endpoints backend, sync engine не должен моделироваться как набор жестко прошитых REST handlers. Внутренняя граница должна оставаться envelope-oriented.

## 11.4. Discovery-specific logic не должна течь вниз

Discovery не должен напрямую писать `pending_ops`, локальные entities или conflict stubs. Максимум — обновить route hints и transport diagnostics.

## 11.5. Frontend-visible surface должен оставаться transport-light

В `frontend-visible-sync-state-model-v1.md` допустимо иметь:
- `transportMode`;
- `connectivity`;
- `lastTransportErrorCode`.

Но недопустимо превращать основной UI в экран низкоуровневой p2p-отладки.

---

## 12. Security и практические ограничения

### 1. Auth идет раньше discovery
Нельзя discovery'ть peer'ов до проверки user/session/scope access.

### 2. Bootstrap artifacts должны быть ограничены по времени и scope
Tickets, pairing codes и route hints должны истекать и быть привязаны к scope/user/session.

### 3. Revocation должна доходить до transport layer
Если replica/session отозвана, transport session должен закрываться, а sync engine получать `blocked` state.

### 4. Metadata minimization
Даже если payload opaque, discovery/relay не должны без необходимости раскрывать лишние workspace/member metadata.

### 5. Browser/platform constraints реальны
На web нельзя проектировать систему так, будто raw sockets, stable background tasks и direct inbound connectivity есть по умолчанию.

### 6. Offline-first не означает offline discovery
Можно быть local-first без гарантии peer discovery в offline-изоляции.

### 7. Debuggability обязательна
Transport layer должен давать нормальные machine-readable ошибки и route diagnostics; иначе любые p2p-проблемы будут выглядеть как "синк иногда сломан".

---

## 13. Frontend и app-logic boundaries

Frontend app logic должен зависеть от следующих integration points:
- `SyncEngine.start()` / `stop()`;
- selectors для app/scope/entity sync state;
- команды `retryPending(scope)`, `requestResync(scope)`, `pauseSync()`, `resumeSync()`;
- optional diagnostics selector `selectTransportState()`.

Frontend app logic **не должен** вызывать напрямую:
- `discoverPeers()` из экранов board/card;
- `openWebRtcSession()`;
- `requestRelayTicket()`;
- transport-specific reconnect loops.

Если позже появится connection-management screen, он должен работать через application service/command слой, а не через прямой доступ к transport backend.

---

## 14. Phased rollout plan

## Phase 0 — текущий MVP baseline
- coordinator-only sync;
- HTTP transport;
- bootstrap = config + auth + replica registration;
- никакого peer discovery.

## Phase 1 — transport-neutral sync engine
- выделить `SyncTransport` interface;
- отделить envelope semantics от HTTP handler shape;
- сохранить тот же frontend-visible sync surface.

## Phase 2 — bootstrap/discovery abstraction
- добавить `SyncBootstrapService`;
- ввести route hints и capability flags;
- разрешить безопасный `coordinator` fallback.

## Phase 3 — relay-assisted mode
- добавить relay ticket / rendezvous;
- научить sync engine переключать `transportMode` без смены conflict policy;
- сохранить canonical coordinator path как fallback.

## Phase 4 — optional direct peer mode
- discovery peer candidates;
- direct peer session после bootstrap;
- relay fallback, если direct path не поднялся.

## Phase 5 — hardening
- revocation propagation;
- protocol/auth hardening;
- richer diagnostics;
- chunked snapshot transport;
- topology-specific operational tuning.

Главный смысл фаз: **transport evolution не должна ломать уже принятые local-first и sync contracts**.

---

## 15. Что важно не перепутать

### 1. `bootstrap` != `sync`
Bootstrap лишь помогает найти путь и стартовать сессию.

### 2. `relay` != `coordinator`
Relay помогает доставке, coordinator задает canonical server-side progress.

### 3. `discovery` != UI feature
Discovery может быть скрытым system layer и не обязан быть пользовательским экраном.

### 4. `direct peer` != обязательный режим
`coordinator_only` остается валидным и безопасным режимом.

### 5. `transport diagnostics` != business conflict
Transport fail не должен маскироваться под domain conflict, а conflict не должен маскироваться под transport timeout.

---

## 16. Короткий итог

Для проекта фиксируется **relay-compatible, transport-neutral sync architecture**:
- UI работает с sync engine, а не с transport internals;
- sync semantics не зависят от того, идет обмен через coordinator, relay или peer;
- bootstrap/discovery/relay выделяются в отдельные роли;
- coordinator остается каноническим sync authority для MVP;
- optional p2p добавляется по фазам как transport evolution, а не как переписывание всей модели.
