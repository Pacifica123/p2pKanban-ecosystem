import type { Board, BoardColumn, Card } from '@/shared/types/api';
import {
  LOCAL_FIRST_SCHEMA_VERSION,
  type LocalBoardSnapshot,
  type LocalCreateCardInput,
  type LocalEntityKind,
  type LocalEntitySyncMetadata,
  type LocalFirstOperation,
  type LocalFirstOperationStatus,
  type LocalMoveCardInput,
  type LocalReorderColumnCardsInput,
  type LocalUpdateCardInput,
} from '@/features/localFirst/types';

const BOARD_SNAPSHOT_PREFIX = 'p2p-planner.local-first.board.';
const OPERATION_QUEUE_KEY = 'p2p-planner.local-first.pending-operations.v1';
const ID_ALIAS_KEY = 'p2p-planner.local-first.id-aliases.v1';
const LOCAL_CARD_PREFIX = 'local_card_';
const LOCAL_OPERATION_PREFIX = 'local_op_';

type Listener = () => void;

const listeners = new Set<Listener>();

export function isLocalCardId(cardId: string) {
  return cardId.startsWith(LOCAL_CARD_PREFIX);
}

export function getLocalFirstEntityKey(kind: LocalEntityKind, entityId: string) {
  return `${kind}:${entityId}`;
}

export function getLocalFirstBoardSnapshotKey(boardId: string) {
  return `${BOARD_SNAPSHOT_PREFIX}${boardId}.v1`;
}

export function getLocalFirstStorage(): Storage | null {
  if (typeof window === 'undefined') return null;

  try {
    return window.localStorage || null;
  } catch {
    return null;
  }
}

export function isLocalFirstStorageAvailable() {
  return getLocalFirstStorage() !== null;
}

export function notifyLocalFirstStore() {
  listeners.forEach((listener) => listener());
}

export function subscribeLocalFirstStore(listener: Listener) {
  listeners.add(listener);

  function handleStorage(event: StorageEvent) {
    if (event.key === OPERATION_QUEUE_KEY || event.key?.startsWith(BOARD_SNAPSHOT_PREFIX)) {
      listener();
    }
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('storage', handleStorage);
  }

  return () => {
    listeners.delete(listener);
    if (typeof window !== 'undefined') {
      window.removeEventListener('storage', handleStorage);
    }
  };
}

function nowIso() {
  return new Date().toISOString();
}

function createId(prefix: string) {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
  return `${prefix}${random}`;
}

function safeReadJson<T>(key: string, fallback: T): T {
  const storage = getLocalFirstStorage();
  if (!storage) return fallback;

  try {
    const raw = storage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function safeWriteJson<T>(key: string, value: T) {
  const storage = getLocalFirstStorage();
  if (!storage) return;
  storage.setItem(key, JSON.stringify(value));
}

export function loadLocalBoardSnapshot(boardId?: string | null): LocalBoardSnapshot | null {
  if (!boardId) return null;
  const snapshot = safeReadJson<(Omit<LocalBoardSnapshot, 'schemaVersion' | 'cards'> & {
    schemaVersion: number;
    cards: Array<Card & { status?: unknown; completedAt?: unknown }>;
  }) | null>(getLocalFirstBoardSnapshotKey(boardId), null);
  if (!snapshot || ![1, LOCAL_FIRST_SCHEMA_VERSION].includes(snapshot.schemaVersion)) return null;
  return {
    ...snapshot,
    schemaVersion: LOCAL_FIRST_SCHEMA_VERSION,
    cards: snapshot.cards.map(stripRemovedCardState),
  };
}

export function saveLocalBoardSnapshot(snapshot: LocalBoardSnapshot) {
  const boardId = snapshot.board?.id || snapshot.cards[0]?.boardId;
  if (!boardId) return;
  safeWriteJson(getLocalFirstBoardSnapshotKey(boardId), snapshot);
  notifyLocalFirstStore();
}

function saveLocalBoardSnapshotByBoardId(boardId: string, snapshot: LocalBoardSnapshot) {
  safeWriteJson(getLocalFirstBoardSnapshotKey(boardId), snapshot);
  notifyLocalFirstStore();
}


export function loadLocalFirstIdAliases() {
  return safeReadJson<Record<string, string>>(ID_ALIAS_KEY, {});
}

function saveLocalFirstIdAliases(aliases: Record<string, string>) {
  safeWriteJson(ID_ALIAS_KEY, aliases);
  notifyLocalFirstStore();
}

export function resolveLocalFirstCardId(cardId: string) {
  return loadLocalFirstIdAliases()[cardId] || cardId;
}

export function loadLocalFirstOperations() {
  return safeReadJson<Array<LocalFirstOperation & { payload: Record<string, unknown> }>>(
    OPERATION_QUEUE_KEY,
    [],
  )
    .map(migrateOperation)
    .filter((operation): operation is LocalFirstOperation => Boolean(operation?.boardId && operation.id));
}

export function saveLocalFirstOperations(operations: LocalFirstOperation[]) {
  safeWriteJson(OPERATION_QUEUE_KEY, operations);
  notifyLocalFirstStore();
}

export function getLocalFirstOperationsForBoard(boardId?: string | null) {
  if (!boardId) return [];
  return loadLocalFirstOperations().filter((operation) => operation.boardId === boardId);
}

function affectedEntityKeys(operation: LocalFirstOperation) {
  const keys = [getLocalFirstEntityKey(operation.entityKind, operation.entityId)];

  if (operation.kind === 'column.cards.reorder') {
    operation.payload.input.items.forEach((item) => keys.push(getLocalFirstEntityKey('card', item.cardId)));
  }

  return Array.from(new Set(keys));
}

export function recomputeLocalSyncMetadata(snapshot: LocalBoardSnapshot, operations: LocalFirstOperation[]) {
  const syncMetadata: Record<string, LocalEntitySyncMetadata> = {};

  operations.forEach((operation) => {
    affectedEntityKeys(operation).forEach((entityKey) => {
      const current = syncMetadata[entityKey];
      const nextStatus = operation.status === 'failed' || current?.status === 'failed' ? 'failed' : 'pending';
      syncMetadata[entityKey] = {
        status: nextStatus,
        operationIds: [...(current?.operationIds || []), operation.id],
        updatedAt: operation.updatedAt,
        error: operation.status === 'failed' ? operation.lastError || 'Operation failed' : current?.error || null,
      };
    });
  });

  return {
    ...snapshot,
    syncMetadata,
  } satisfies LocalBoardSnapshot;
}

function nextCardPosition(cards: Card[], columnId: string) {
  const columnCards = cards.filter((card) => card.columnId === columnId);
  const maxPosition = columnCards.reduce((max, card) => Math.max(max, card.position || 0), 0);
  return maxPosition + 1000;
}

function stripRemovedCardState(
  value: Card & { status?: unknown; completedAt?: unknown },
): Card {
  const { status: _status, completedAt: _completedAt, ...card } = value;
  return card;
}

function stripRemovedCardInput<T extends Record<string, unknown>>(value: T) {
  const { status: _status, completedAt: _completedAt, ...input } = value;
  return input;
}

function migrateOperation(
  operation: LocalFirstOperation & { payload: Record<string, unknown> },
): LocalFirstOperation | null {
  if (operation.kind === 'card.create') {
    const payload = operation.payload as unknown as LocalFirstOperation['payload'] & {
      input: Record<string, unknown>;
      tempCard: Card & { status?: unknown; completedAt?: unknown };
    };
    return {
      ...operation,
      payload: {
        ...payload,
        input: stripRemovedCardInput(payload.input),
        tempCard: stripRemovedCardState(payload.tempCard),
      },
    } as unknown as LocalFirstOperation;
  }
  if (operation.kind === 'card.update') {
    const payload = operation.payload as unknown as { input: Record<string, unknown> };
    const input = stripRemovedCardInput(payload.input);
    if (!Object.keys(input).length) return null;
    return { ...operation, payload: { input } } as unknown as LocalFirstOperation;
  }
  return operation as LocalFirstOperation;
}

function createTempCard(boardId: string, input: LocalCreateCardInput, cards: Card[]) {
  const timestamp = nowIso();
  return {
    id: createId(LOCAL_CARD_PREFIX),
    boardId,
    columnId: input.columnId,
    parentCardId: null,
    title: input.title,
    description: input.description || null,
    priority: input.priority ?? null,
    position: nextCardPosition(cards, input.columnId),
    startAt: null,
    dueAt: null,
    isArchived: false,
    labelIds: [],
    checklistCount: 0,
    checklistCompletedItemCount: 0,
    commentCount: 0,
    createdByUserId: null,
    createdAt: timestamp,
    updatedAt: timestamp,
    archivedAt: null,
  } satisfies Card;
}

export function applyLocalFirstOperation(snapshot: LocalBoardSnapshot, operation: LocalFirstOperation) {
  const timestamp = operation.updatedAt || nowIso();

  if (operation.kind === 'card.create') {
    const exists = snapshot.cards.some((card) => card.id === operation.payload.tempCard.id);
    return {
      ...snapshot,
      cards: exists ? snapshot.cards : [...snapshot.cards, operation.payload.tempCard],
      cachedAt: timestamp,
    } satisfies LocalBoardSnapshot;
  }

  if (operation.kind === 'card.update') {
    return {
      ...snapshot,
      cards: snapshot.cards.map((card) => card.id === operation.entityId ? { ...card, ...operation.payload.input, updatedAt: timestamp } : card),
      cachedAt: timestamp,
    } satisfies LocalBoardSnapshot;
  }

  if (operation.kind === 'card.move') {
    return {
      ...snapshot,
      cards: snapshot.cards.map((card) => {
        if (card.id !== operation.entityId) return card;
        return {
          ...card,
          columnId: operation.payload.input.targetColumnId,
          position: operation.payload.input.position ?? nextCardPosition(snapshot.cards, operation.payload.input.targetColumnId),
          updatedAt: timestamp,
        };
      }),
      cachedAt: timestamp,
    } satisfies LocalBoardSnapshot;
  }

  if (operation.kind === 'column.cards.reorder') {
    const positions = new Map(operation.payload.input.items.map((item) => [item.cardId, item.position]));
    return {
      ...snapshot,
      cards: snapshot.cards.map((card) => positions.has(card.id) ? { ...card, position: positions.get(card.id)!, updatedAt: timestamp } : card),
      cachedAt: timestamp,
    } satisfies LocalBoardSnapshot;
  }

  return snapshot;
}

export function seedLocalBoardSnapshotFromServer(input: {
  workspaceId?: string | null;
  board: Board;
  columns: BoardColumn[];
  cards: Card[];
}) {
  const timestamp = nowIso();
  const operations = getLocalFirstOperationsForBoard(input.board.id);
  let snapshot: LocalBoardSnapshot = {
    schemaVersion: LOCAL_FIRST_SCHEMA_VERSION,
    workspace: {
      id: input.workspaceId || input.board.workspaceId,
      value: null,
      cachedAt: timestamp,
    },
    board: input.board,
    columns: input.columns,
    cards: input.cards,
    cachedAt: timestamp,
    lastServerRefreshAt: timestamp,
    syncMetadata: {},
  };

  operations.forEach((operation) => {
    snapshot = applyLocalFirstOperation(snapshot, operation);
  });

  snapshot = recomputeLocalSyncMetadata(snapshot, operations);
  saveLocalBoardSnapshotByBoardId(input.board.id, snapshot);
  return snapshot;
}

function ensureSnapshotForBoard(boardId: string) {
  const existing = loadLocalBoardSnapshot(boardId);
  if (existing) return existing;

  const timestamp = nowIso();
  return {
    schemaVersion: LOCAL_FIRST_SCHEMA_VERSION,
    workspace: {
      id: '',
      value: null,
      cachedAt: timestamp,
    },
    board: null,
    columns: [],
    cards: [],
    cachedAt: timestamp,
    lastServerRefreshAt: null,
    syncMetadata: {},
  } satisfies LocalBoardSnapshot;
}

function appendLocalFirstOperation(operation: LocalFirstOperation) {
  const operations = loadLocalFirstOperations();
  saveLocalFirstOperations([...operations, operation]);
  return operation;
}

function persistOperationWithSnapshot(boardId: string, operation: LocalFirstOperation) {
  appendLocalFirstOperation(operation);
  const boardOperations = getLocalFirstOperationsForBoard(boardId);
  const snapshot = recomputeLocalSyncMetadata(applyLocalFirstOperation(ensureSnapshotForBoard(boardId), operation), boardOperations);
  saveLocalBoardSnapshotByBoardId(boardId, snapshot);
}

export function enqueueCreateCardOperation(boardId: string, input: LocalCreateCardInput) {
  const snapshot = ensureSnapshotForBoard(boardId);
  const tempCard = createTempCard(boardId, input, snapshot.cards);
  const timestamp = nowIso();
  const operation: LocalFirstOperation = {
    id: createId(LOCAL_OPERATION_PREFIX),
    boardId,
    entityKind: 'card',
    entityId: tempCard.id,
    kind: 'card.create',
    status: 'pending',
    payload: { input, tempCard },
    createdAt: timestamp,
    updatedAt: timestamp,
    attempts: 0,
    lastError: null,
  };

  persistOperationWithSnapshot(boardId, operation);
  return tempCard;
}

export function enqueueUpdateCardOperation(boardId: string, cardId: string, input: LocalUpdateCardInput) {
  const timestamp = nowIso();
  persistOperationWithSnapshot(boardId, {
    id: createId(LOCAL_OPERATION_PREFIX),
    boardId,
    entityKind: 'card',
    entityId: cardId,
    kind: 'card.update',
    status: 'pending',
    payload: { input },
    createdAt: timestamp,
    updatedAt: timestamp,
    attempts: 0,
    lastError: null,
  });
}

export function enqueueMoveCardOperation(boardId: string, cardId: string, input: LocalMoveCardInput) {
  const timestamp = nowIso();
  persistOperationWithSnapshot(boardId, {
    id: createId(LOCAL_OPERATION_PREFIX),
    boardId,
    entityKind: 'card',
    entityId: cardId,
    kind: 'card.move',
    status: 'pending',
    payload: { input },
    createdAt: timestamp,
    updatedAt: timestamp,
    attempts: 0,
    lastError: null,
  });
}

export function enqueueReorderColumnCardsOperation(boardId: string, columnId: string, input: LocalReorderColumnCardsInput) {
  const timestamp = nowIso();
  persistOperationWithSnapshot(boardId, {
    id: createId(LOCAL_OPERATION_PREFIX),
    boardId,
    entityKind: 'column',
    entityId: columnId,
    kind: 'column.cards.reorder',
    status: 'pending',
    payload: { input },
    createdAt: timestamp,
    updatedAt: timestamp,
    attempts: 0,
    lastError: null,
  });
}

function replaceCardIdInOperation(operation: LocalFirstOperation, fromCardId: string, toCardId: string): LocalFirstOperation {
  const entityId = operation.entityId === fromCardId ? toCardId : operation.entityId;

  if (operation.kind === 'column.cards.reorder') {
    return {
      ...operation,
      entityId,
      payload: {
        input: {
          items: operation.payload.input.items.map((item) => item.cardId === fromCardId ? { ...item, cardId: toCardId } : item),
        },
      },
    };
  }

  return {
    ...operation,
    entityId,
  };
}

export function replaceLocalCardAfterCreate(boardId: string, tempCardId: string, serverCard: Card) {
  const snapshot = loadLocalBoardSnapshot(boardId);
  if (snapshot) {
    const nextCards = snapshot.cards.map((card) => card.id === tempCardId ? serverCard : card);
    const nextMetadata: LocalBoardSnapshot['syncMetadata'] = {};
    Object.entries(snapshot.syncMetadata).forEach(([key, value]) => {
      nextMetadata[key === getLocalFirstEntityKey('card', tempCardId) ? getLocalFirstEntityKey('card', serverCard.id) : key] = value;
    });
    saveLocalBoardSnapshotByBoardId(boardId, {
      ...snapshot,
      cards: nextCards,
      syncMetadata: nextMetadata,
      cachedAt: nowIso(),
    });
  }

  const aliases = loadLocalFirstIdAliases();
  saveLocalFirstIdAliases({ ...aliases, [tempCardId]: serverCard.id });

  const operations = loadLocalFirstOperations().map((operation) =>
    operation.boardId === boardId ? replaceCardIdInOperation(operation, tempCardId, serverCard.id) : operation,
  );
  saveLocalFirstOperations(operations);
}

export function removeLocalFirstOperation(operationId: string) {
  const operations = loadLocalFirstOperations();
  const removed = operations.find((operation) => operation.id === operationId);
  const nextOperations = operations.filter((operation) => operation.id !== operationId);
  saveLocalFirstOperations(nextOperations);

  if (removed) {
    const snapshot = loadLocalBoardSnapshot(removed.boardId);
    if (snapshot) {
      saveLocalBoardSnapshotByBoardId(removed.boardId, recomputeLocalSyncMetadata(snapshot, nextOperations.filter((operation) => operation.boardId === removed.boardId)));
    }
  }
}

export function markLocalFirstOperationStatus(operationId: string, status: LocalFirstOperationStatus, error?: string | null) {
  const timestamp = nowIso();
  const operations = loadLocalFirstOperations().map((operation) =>
    operation.id === operationId
      ? {
          ...operation,
          status,
          updatedAt: timestamp,
          attempts: status === 'failed' ? operation.attempts + 1 : operation.attempts,
          lastError: status === 'failed' ? error || 'Operation failed' : null,
        }
      : operation,
  );
  saveLocalFirstOperations(operations);

  const updated = operations.find((operation) => operation.id === operationId);
  if (updated) {
    const snapshot = loadLocalBoardSnapshot(updated.boardId);
    if (snapshot) {
      saveLocalBoardSnapshotByBoardId(updated.boardId, recomputeLocalSyncMetadata(snapshot, operations.filter((operation) => operation.boardId === updated.boardId)));
    }
  }
}

export function markFailedOperationsForRetry(boardId?: string | null) {
  const timestamp = nowIso();
  const operations = loadLocalFirstOperations().map((operation) => {
    if (operation.status !== 'failed') return operation;
    if (boardId && operation.boardId !== boardId) return operation;
    return {
      ...operation,
      status: 'pending' as const,
      updatedAt: timestamp,
      lastError: null,
    };
  });
  saveLocalFirstOperations(operations);

  const affectedBoardIds = Array.from(new Set(operations.map((operation) => operation.boardId)));
  affectedBoardIds.forEach((currentBoardId) => {
    const snapshot = loadLocalBoardSnapshot(currentBoardId);
    if (snapshot) {
      saveLocalBoardSnapshotByBoardId(currentBoardId, recomputeLocalSyncMetadata(snapshot, operations.filter((operation) => operation.boardId === currentBoardId)));
    }
  });
}
