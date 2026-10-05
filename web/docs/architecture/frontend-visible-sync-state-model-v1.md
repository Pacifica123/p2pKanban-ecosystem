# Frontend-visible sync state model v1

- Статус: Draft v1
- Дата: 2026-04-12
- Назначение: определить, какое sync-состояние должен видеть frontend и как его показывать пользователю без утечки лишнего transport/internal шума.

> Этот документ описывает не внутреннюю серверную схему таблиц, а именно client-side surface model для UI и application state. Он продолжает local-first слой и sync implementation plan.

---

## 1. Принцип

Frontend не должен работать с sync как с набором случайных флажков типа `isFetching`.

Нужна отдельная модель состояния, которая:
- отражает здоровье sync engine;
- показывает, можно ли доверять текущему локальному экрану;
- различает offline, pending, failed и needs_snapshot;
- дает достаточно информации для UI, но не заставляет экран знать детали протокола.

---

## 2. Уровни sync state

Frontend-visible sync state делится на три уровня:

### 1. App-level
Состояние сети, реплики и sync engine в целом.

### 2. Scope-level
Состояние конкретного `global` или `workspace` scope.

### 3. Entity-level
Состояние конкретной сущности в local store.

---

## 3. App-level model

```ts
export type NetworkState = 'online' | 'offline' | 'degraded';
export type ReplicaState = 'unknown' | 'registering' | 'ready' | 'revoked' | 'error';
export type SyncEnginePhase =
  | 'idle'
  | 'hydrating'
  | 'pushing'
  | 'pulling'
  | 'reconciling'
  | 'backoff'
  | 'paused'
  | 'needs_snapshot';

export type TransportMode = 'coordinator' | 'relay_assisted' | 'direct_peer';

export interface AppSyncState {
  network: NetworkState;
  replica: ReplicaState;
  enginePhase: SyncEnginePhase;
  transportMode: TransportMode;
  transportConnectivity: 'disconnected' | 'connecting' | 'connected' | 'degraded';
  pendingCount: number;
  failedCount: number;
  lastSuccessfulPushAt: string | null;
  lastSuccessfulPullAt: string | null;
  lastSuccessfulSyncAt: string | null;
  blockingIssue: SyncBlockingIssue | null;
  hasManualAction: boolean;
}

export type SyncBlockingIssue =
  | 'auth_required'
  | 'replica_revoked'
  | 'snapshot_required'
  | 'storage_unavailable'
  | 'corrupted_cursor';
```

### Как это читать

- `network` отвечает за связность.
- `replica` отвечает за готовность текущей реплики к sync.
- `enginePhase` показывает, что делает sync engine прямо сейчас.
- `transportMode` и `transportConnectivity` нужны для diagnostics и возможного future connection-management surface, но не должны менять domain UX.
- `pendingCount` и `failedCount` нужны для понятных UI-индикаторов.
- `blockingIssue` показывает, что автоматический фон не может продолжаться без вмешательства.

---

## 4. Scope-level model

```ts
export type SyncScopeType = 'global' | 'workspace';
export type HydrationState =
  | 'empty'
  | 'cold_hydrating'
  | 'warm'
  | 'hydrated'
  | 'stale'
  | 'offline_unavailable';
export type ScopeHealth = 'healthy' | 'degraded' | 'blocked';

export interface SyncScopeState {
  scopeType: SyncScopeType;
  scopeId: string | null;
  hydration: HydrationState;
  health: ScopeHealth;
  enginePhase: SyncEnginePhase;
  cursorLastServerOrder: number | null;
  pendingCount: number;
  failedCount: number;
  hasMoreToPull: boolean;
  lastSuccessfulPullAt: string | null;
  lastSuccessfulPushAt: string | null;
  lastErrorCode: string | null;
  requiresSnapshot: boolean;
}
```

### Для чего это нужно

`AppSyncState` слишком общий. Экрану workspace/board нужен локальный ответ на вопросы:
- этот workspace уже гидрирован или еще пустой;
- есть ли незасинканные локальные изменения именно здесь;
- scope просто stale или уже blocked;
- нужен ли recovery path.

---

## 5. Entity-level model

Entity-level состояние живет рядом с `entity_meta` и проецируется в UI через селекторы.

```ts
export type EntitySyncStatus =
  | 'synced'
  | 'pending_create'
  | 'pending_update'
  | 'pending_delete'
  | 'failed'
  | 'conflict_stub';

export type ConflictKind =
  | 'same_field_lww_loss'
  | 'delete_vs_update'
  | 'parent_deleted'
  | 'permission_denied'
  | 'unique_constraint'
  | 'structural_conflict';

export interface EntitySyncMeta {
  entityType: string;
  entityId: string;
  syncStatus: EntitySyncStatus;
  dirtyFields: string[];
  lastLocalWriteAt: string | null;
  lastServerSyncAt: string | null;
  baseServerOrder: number | null;
  hasRetryableError: boolean;
  lastErrorCode: string | null;
  conflictKind: ConflictKind | null;
  requiresManualResolution: boolean;
  canCopyLosingValue: boolean;
  losingValuePreview: string | null;
}
```

### Что важно

- это **не transport DTO**;
- это не обязано полностью совпадать с серверной БД;
- это нормализованная frontend-видимая проекция sync-статуса сущности.
- `conflict_stub` означает не обязательно неразрешенный merge: чаще canonical state уже выбран, но пользователю еще нужно показать review/loss surface;
- `requiresManualResolution` нужен только для ограниченного набора high-trust кейсов, а не для каждого LWW.

---

## 6. Minimal user-visible statuses

Пользователь не должен видеть термины вроде `cursor`, `replicaSeq`, `serverOrder` в обычном интерфейсе. То же самое относится к `relay ticket`, `peer candidate`, `ICE` и другим transport-внутренностям.

Минимальный рекомендуемый набор человеко-понятных статусов:
- `Offline`
- `Saved locally`
- `Syncing`
- `Changes pending`
- `Sync failed`
- `Needs review`
- `Needs refresh`
- `Sync paused`

Отдельно для recovery case:
- `Needs resync`

---

## 7. Mapping internal state -> UI copy

### App banner / global status

| Internal state | UI surface |
|---|---|
| `network = offline`, `pendingCount = 0` | `Offline` |
| `network = offline`, `pendingCount > 0` | `Offline · changes pending` |
| `enginePhase = pushing / pulling / reconciling` | `Syncing…` |
| `transportConnectivity = degraded`, not blocked | `Connection unstable` |
| `failedCount > 0`, not blocked | `Some changes failed to sync` |
| `blockingIssue = snapshot_required` | `Needs resync` |
| `replica = revoked` | `Sync paused` |

### Entity badge

| EntitySyncStatus | Recommended badge |
|---|---|
| `synced` | no badge or subtle synced marker |
| `pending_create` | `Saved locally` |
| `pending_update` | `Saved locally` |
| `pending_delete` | `Pending deletion` |
| `failed` | `Sync failed` |
| `conflict_stub` | `Needs review` |

---

## 8. Distinguish these states clearly

Frontend обязан различать следующие состояния и не сливать их:

### A. `empty`
Данных реально нет.

### B. `cold_hydrating`
Данных еще нет, но идет первичная гидрация.

### C. `warm`
Есть локальные данные, но scope еще проверяется/освежается.

### D. `stale`
Есть локальные данные, но они давно не подтверждались сервером.

### E. `offline_unavailable`
Нужных данных нет локально и сеть недоступна.

### F. `needs_snapshot`
Обычный incremental path больше невалиден, нужен recovery.

Эти состояния реально разные по UX и не должны сводиться к одному boolean `isLoading`.

---

## 9. Scope status rules

### `healthy`
- sync engine может нормально push/pull;
- cursor валиден;
- нет blocking issue.

### `degraded`
- локальные данные доступны;
- retry/backoff идет;
- пользователь может продолжать работать;
- часть изменений еще не подтверждена сервером.

### `blocked`
- без re-auth, snapshot recovery или storage fix продолжать normal sync нельзя.

---

## 10. When frontend should show global blocking UI

Глобально блокирующий UI нужен только если:
- local store недоступен или поврежден;
- replica revoked / auth invalid and sync cannot continue;
- scope requires destructive recovery before safe work;
- приложение не может даже открыть локальные данные.

Во всех остальных случаях предпочтителен мягкий surface:
- inline status;
- top banner;
- subtle badge;
- retry action.

Local-first UX не должен разваливаться в full-screen error только из-за временной сети.

---

## 11. Suggested store shape

```ts
export interface SyncStateStore {
  app: AppSyncState;
  scopes: Record<string, SyncScopeState>;
  entities: Record<string, EntitySyncMeta>;
}
```

Где ключи могут быть такими:
- app: один singleton;
- scope key: `global` или `workspace:<id>`;
- entity key: `<entityType>:<entityId>`.

---

## 12. Selectors the frontend will need

Минимальный набор селекторов:
- `selectAppSyncState()`
- `selectScopeSyncState(scopeKey)`
- `selectEntitySyncMeta(entityType, entityId)`
- `selectPendingCountForScope(scopeKey)`
- `selectHasBlockingSyncIssue()`
- `selectNeedsSnapshot(scopeKey)`
- `selectTransportState()`
- `selectIsEntityUnsynced(entityType, entityId)`

Это важнее, чем напрямую читать сырые записи `pending_ops` на каждом экране.

---

## 13. Interaction rules for screens

### Workspace/board list screens
Должны уметь показать:
- warm cached content;
- background syncing;
- offline mode;
- pending local changes without перерендера из network DTO.

### Board screen
Должен уметь показать:
- локально созданные/перемещенные карточки;
- pending reorder state;
- failure badge на проблемной карточке/колонке, а не только где-то в глобальном статусе.

### Appearance screens
Должны различать:
- draft preview;
- saved locally;
- syncing;
- sync failed.

### Activity/history screens
Не должны трактоваться как основной sync state surface.
Они могут иметь собственную hydration-state модель, но не заменяют sync engine status.

---

## 14. Persistence rules

Не все frontend-visible sync state нужно хранить одинаково.

### Persisted
- `replicaId`
- cursors
- entity sync metadata
- pending/failure markers
- last successful sync timestamps
- scope hydration markers

### In-memory only
- current transient `enginePhase`
- active request counters
- temporary retry timer info
- ephemeral toasts and banners

Это дает reload-safe состояние без загрязнения persistent store transient-шумом.

---

## 15. Minimal success criteria

Модель считается достаточной для этапа, если frontend умеет:
- показать cached screen до сети;
- показать `Saved locally` после локальной мутации;
- показать `Syncing` во время фонового цикла;
- показать `Sync failed` без потери локального состояния;
- показать `Needs resync`, если scope больше не может жить на обычном cursor-based pull.

---

## 16. Conflict-aware UI hints

`conflict_stub` не должен автоматически открывать modal на весь экран. Предпочтительный v1 surface:
- badge `Needs review` на entity row/card;
- inline banner в details view;
- action buttons `Copy my text`, `Discard local change`, `Retry after edit` там, где это применимо;
- sync panel entry для накопленных unresolved review items.

Manual resolution нужна только когда `requiresManualResolution = true`. Для простого `LWW per field` без meaningful loss отдельный UX не обязателен.

---

## 17. Короткий итог

Frontend-visible sync state в проекте — это отдельная нормализованная модель, а не набор случайных loading-флагов.

Она должна покрывать:
- app-level health;
- scope-level hydration/sync status;
- entity-level pending/failure markers;
- мягкий local-first UX при временной потере сети;
- явный recovery surface для `needs_snapshot` и других blocking issues.
