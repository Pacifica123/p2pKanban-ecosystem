import type {
  Board,
  BoardAppearanceSettings,
  BoardColumn,
  Card,
  Checklist,
  ChecklistItem,
  UpdateBoardAppearanceRequest,
} from '../../shared/types/api';

export const LOCAL_SCHEMA_VERSION = 6;

export interface LocalBoardSnapshot {
  schemaVersion: typeof LOCAL_SCHEMA_VERSION;
  workspaceId: string;
  board: Board;
  appearance: BoardAppearanceSettings;
  columns: BoardColumn[];
  cards: Card[];
  checklistsByCardId: Record<string, Checklist[]>;
  checklistsHydratedAt: string | null;
  cachedAt: string;
  lastServerRefreshAt: string | null;
}

interface OperationBase {
  actor?: {userId: string | null; displayName: string | null};
  id: string;
  boardId: string;
  entityId: string;
  status: 'pending' | 'relay_pending' | 'failed';
  accessEpoch?: number;
  createdAt: string;
  attempts: number;
  lastError: string | null;
}

export interface CreateCardOperation extends OperationBase {
  kind: 'card.create';
  payload: {
    input: {
      title: string;
      description?: string;
      columnId: string;
      priority?: Card['priority'];
    };
    tempCard: Card;
  };
}

export interface UpdateCardOperation extends OperationBase {
  kind: 'card.update';
  payload: {
    input: Partial<Pick<
      Card,
      'title' | 'description' | 'priority' | 'startAt' | 'dueAt'
    >>;
  };
}

export interface UpdateBoardAppearanceOperation extends OperationBase {
  kind: 'board.appearance.update';
  payload: {
    input: UpdateBoardAppearanceRequest;
    optimistic: BoardAppearanceSettings;
  };
}

export interface MoveCardOperation extends OperationBase {
  kind: 'card.move';
  payload: {
    input: {
      targetColumnId: string;
      position?: number | null;
    };
  };
}

export interface ArchiveCardOperation extends OperationBase {
  kind: 'card.archive' | 'card.unarchive';
  payload: Record<string, never>;
}

export interface DeleteCardOperation extends OperationBase {
  kind: 'card.delete';
  payload: { card: Card };
}

export interface CreateChecklistOperation extends OperationBase {
  kind: 'checklist.create';
  payload: {
    cardId: string;
    input: { title: string; position?: number | null };
    tempChecklist: Checklist;
  };
}

export interface UpdateChecklistOperation extends OperationBase {
  kind: 'checklist.update';
  payload: {
    cardId: string;
    input: { title?: string; position?: number | null };
  };
}

export interface DeleteChecklistOperation extends OperationBase {
  kind: 'checklist.delete';
  payload: { cardId: string };
}

export interface CreateChecklistItemOperation extends OperationBase {
  kind: 'checklist.item.create';
  payload: {
    cardId: string;
    checklistId: string;
    input: { title: string; position?: number | null };
    tempItem: ChecklistItem;
  };
}

export interface UpdateChecklistItemOperation extends OperationBase {
  kind: 'checklist.item.update';
  payload: {
    cardId: string;
    checklistId: string;
    input: {
      title?: string;
      position?: number | null;
      isDone?: boolean | null;
    };
  };
}

export interface DeleteChecklistItemOperation extends OperationBase {
  kind: 'checklist.item.delete';
  payload: {
    cardId: string;
    checklistId: string;
  };
}

export type LocalOperation =
  | UpdateBoardAppearanceOperation
  | CreateCardOperation
  | UpdateCardOperation
  | MoveCardOperation
  | ArchiveCardOperation
  | DeleteCardOperation
  | CreateChecklistOperation
  | UpdateChecklistOperation
  | DeleteChecklistOperation
  | CreateChecklistItemOperation
  | UpdateChecklistItemOperation
  | DeleteChecklistItemOperation;

export type ChecklistOperation =
  | CreateChecklistOperation
  | UpdateChecklistOperation
  | DeleteChecklistOperation
  | CreateChecklistItemOperation
  | UpdateChecklistItemOperation
  | DeleteChecklistItemOperation;

export function isChecklistOperation(
  operation: LocalOperation,
): operation is ChecklistOperation {
  return operation.kind.startsWith('checklist.');
}

function checklistCounts(checklists: Checklist[]) {
  const items = checklists.flatMap((checklist) => checklist.items);
  return {
    checklistCount: checklists.length,
    checklistItemCount: items.length,
    checklistCompletedItemCount: items.filter((item) => item.isDone).length,
  };
}

function nextPosition(values: Array<{ position: number }>) {
  return values.reduce((highest, value) => Math.max(highest, value.position), 0) + 1000;
}

function withChecklists(
  snapshot: LocalBoardSnapshot,
  cardId: string,
  checklists: Checklist[],
  timestamp: string,
) {
  return {
    ...snapshot,
    cards: snapshot.cards.map((card) => card.id === cardId
      ? { ...card, ...checklistCounts(checklists), updatedAt: timestamp }
      : card),
    checklistsByCardId: {
      ...snapshot.checklistsByCardId,
      [cardId]: checklists,
    },
    checklistsHydratedAt: [snapshot.checklistsHydratedAt, timestamp]
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) || timestamp,
    cachedAt: timestamp,
  };
}

export function replaceChecklist(
  snapshot: LocalBoardSnapshot,
  cardId: string,
  checklist: Checklist,
) {
  const current = snapshot.checklistsByCardId[cardId] || [];
  const exists = current.some((candidate) => candidate.id === checklist.id);
  const checklists = exists
    ? current.map((candidate) => candidate.id === checklist.id ? checklist : candidate)
    : [...current, checklist];
  return withChecklists(snapshot, cardId, checklists, checklist.updatedAt);
}

export function replaceChecklistItem(
  snapshot: LocalBoardSnapshot,
  cardId: string,
  item: ChecklistItem,
) {
  const checklists = (snapshot.checklistsByCardId[cardId] || []).map((checklist) => (
    checklist.id === item.checklistId
      ? {
        ...checklist,
        items: checklist.items.some((candidate) => candidate.id === item.id)
          ? checklist.items.map((candidate) => candidate.id === item.id ? item : candidate)
          : [...checklist.items, item],
        updatedAt: item.updatedAt,
      }
      : checklist
  ));
  return withChecklists(snapshot, cardId, checklists, item.updatedAt);
}

function nextCardPosition(cards: Card[], columnId: string) {
  return nextPosition(
    cards.filter((card) => card.columnId === columnId && !card.isArchived),
  );
}

export function operationCardId(operation: LocalOperation) {
  if (operation.kind === 'board.appearance.update') return operation.entityId;
  return isChecklistOperation(operation)
    ? operation.payload.cardId
    : operation.entityId;
}

export function operationAffectsCard(operation: LocalOperation, cardId: string) {
  return operationCardId(operation) === cardId;
}

export function applyOperation(
  snapshot: LocalBoardSnapshot,
  operation: LocalOperation,
): LocalBoardSnapshot {
  const timestamp = operation.createdAt;

  if (operation.kind === 'board.appearance.update') {
    return {
      ...snapshot,
      appearance: operation.payload.optimistic,
      cachedAt: timestamp,
    };
  }

  if (operation.kind === 'card.create') {
    const exists = snapshot.cards.some((card) => card.id === operation.payload.tempCard.id);
    return {
      ...snapshot,
      cards: exists ? snapshot.cards : [...snapshot.cards, operation.payload.tempCard],
      checklistsByCardId: {
        ...snapshot.checklistsByCardId,
        [operation.payload.tempCard.id]:
          snapshot.checklistsByCardId[operation.payload.tempCard.id] || [],
      },
      cachedAt: timestamp,
    };
  }

  if (operation.kind === 'card.update') {
    return {
      ...snapshot,
      cards: snapshot.cards.map((card) => card.id === operation.entityId
        ? { ...card, ...operation.payload.input, updatedAt: timestamp }
        : card),
      cachedAt: timestamp,
    };
  }

  if (operation.kind === 'card.move') {
    const position = operation.payload.input.position
      ?? nextCardPosition(snapshot.cards, operation.payload.input.targetColumnId);
    return {
      ...snapshot,
      cards: snapshot.cards.map((card) => card.id === operation.entityId
        ? {
          ...card,
          columnId: operation.payload.input.targetColumnId,
          position,
          updatedAt: timestamp,
        }
        : card),
      cachedAt: timestamp,
    };
  }

  if (operation.kind === 'card.archive' || operation.kind === 'card.unarchive') {
    const archived = operation.kind === 'card.archive';
    return {
      ...snapshot,
      cards: snapshot.cards.map((card) => card.id === operation.entityId
        ? {
          ...card,
          isArchived: archived,
          archivedAt: archived ? timestamp : null,
          updatedAt: timestamp,
        }
        : card),
      cachedAt: timestamp,
    };
  }

  if (operation.kind === 'card.delete') {
    const checklistsByCardId = { ...snapshot.checklistsByCardId };
    delete checklistsByCardId[operation.entityId];
    return {
      ...snapshot,
      cards: snapshot.cards.filter((card) => card.id !== operation.entityId),
      checklistsByCardId,
      cachedAt: timestamp,
    };
  }

  const cardId = operation.payload.cardId;
  const current = snapshot.checklistsByCardId[cardId] || [];

  if (operation.kind === 'checklist.create') {
    const exists = current.some((checklist) => checklist.id === operation.entityId);
    return withChecklists(
      snapshot,
      cardId,
      exists ? current : [...current, operation.payload.tempChecklist],
      timestamp,
    );
  }

  if (operation.kind === 'checklist.update') {
    return withChecklists(
      snapshot,
      cardId,
      current.map((checklist) => checklist.id === operation.entityId
        ? {
          ...checklist,
          ...operation.payload.input,
          position: operation.payload.input.position ?? checklist.position,
          updatedAt: timestamp,
        }
        : checklist),
      timestamp,
    );
  }

  if (operation.kind === 'checklist.delete') {
    return withChecklists(
      snapshot,
      cardId,
      current.filter((checklist) => checklist.id !== operation.entityId),
      timestamp,
    );
  }

  if (operation.kind === 'checklist.item.create') {
    return withChecklists(
      snapshot,
      cardId,
      current.map((checklist) => checklist.id === operation.payload.checklistId
        ? {
          ...checklist,
          items: checklist.items.some((item) => item.id === operation.entityId)
            ? checklist.items
            : [...checklist.items, operation.payload.tempItem],
          updatedAt: timestamp,
        }
        : checklist),
      timestamp,
    );
  }

  if (operation.kind === 'checklist.item.update') {
    return withChecklists(
      snapshot,
      cardId,
      current.map((checklist) => checklist.id === operation.payload.checklistId
        ? {
          ...checklist,
          items: checklist.items.map((item) => {
            if (item.id !== operation.entityId) return item;
            const isDone = operation.payload.input.isDone ?? item.isDone;
            return {
              ...item,
              ...operation.payload.input,
              position: operation.payload.input.position ?? item.position,
              isDone,
              completedAt: operation.payload.input.isDone === undefined
                || operation.payload.input.isDone === null
                ? item.completedAt
                : isDone ? timestamp : null,
              updatedAt: timestamp,
            };
          }),
          updatedAt: timestamp,
        }
        : checklist),
      timestamp,
    );
  }

  return withChecklists(
    snapshot,
    cardId,
    current.map((checklist) => checklist.id === operation.payload.checklistId
      ? {
        ...checklist,
        items: checklist.items.filter((item) => item.id !== operation.entityId),
        updatedAt: timestamp,
      }
      : checklist),
    timestamp,
  );
}

export function applyOperations(snapshot: LocalBoardSnapshot, operations: LocalOperation[]) {
  return operations
    .filter((operation) => operation.boardId === snapshot.board.id)
    .reduce(applyOperation, snapshot);
}

function remapCardIdInOperation(
  operation: LocalOperation,
  fromCardId: string,
  toCardId: string,
): LocalOperation {
  if (isChecklistOperation(operation)) {
    return operation.payload.cardId === fromCardId
      ? {
        ...operation,
        payload: { ...operation.payload, cardId: toCardId },
      } as LocalOperation
      : operation;
  }
  return operation.entityId === fromCardId
    ? { ...operation, entityId: toCardId }
    : operation;
}

export function mergeBoardSnapshots(
  server: LocalBoardSnapshot,
  relay: LocalBoardSnapshot | null,
  relayState?: {
    tombstones?: Record<string, unknown>;
    checklistTombstones?: Record<string, unknown>;
    checklistItemTombstones?: Record<string, unknown>;
  },
) {
  if (!relay || relay.board.id !== server.board.id) return server;
  const cardTombstones = relayState?.tombstones || {};
  const checklistTombstones = relayState?.checklistTombstones || {};
  const checklistItemTombstones = relayState?.checklistItemTombstones || {};
  const byId = new Map(
    server.cards
      .filter((card) => !cardTombstones[card.id])
      .map((card) => [card.id, card]),
  );
  for (const card of relay.cards) {
    if (cardTombstones[card.id]) continue;
    const current = byId.get(card.id);
    if (!current || card.updatedAt.localeCompare(current.updatedAt) > 0) {
      byId.set(card.id, card);
    }
  }
  const cards = [...byId.values()];
  const checklistsByCardId = Object.fromEntries(cards.map((card) => {
    const byChecklistId = new Map<string, Checklist>();
    const sources = [
      ...(server.checklistsByCardId[card.id] || []),
      ...(relay.checklistsByCardId[card.id] || []),
    ];
    for (const checklist of sources) {
      if (checklistTombstones[checklist.id]) continue;
      const current = byChecklistId.get(checklist.id);
      const preferred = !current || checklist.updatedAt.localeCompare(current.updatedAt) > 0
        ? checklist
        : current;
      const items = new Map<string, ChecklistItem>();
      for (const item of [...(current?.items || []), ...(checklist.items || [])]) {
        if (checklistItemTombstones[item.id]) continue;
        const existing = items.get(item.id);
        if (!existing || item.updatedAt.localeCompare(existing.updatedAt) > 0) {
          items.set(item.id, item);
        }
      }
      byChecklistId.set(checklist.id, {
        ...preferred,
        items: [...items.values()].sort((left, right) => left.position - right.position),
      });
    }
    return [
      card.id,
      [...byChecklistId.values()].sort((left, right) => left.position - right.position),
    ];
  }));
  return {
    ...server,
    appearance: (relay.appearance.updatedAt || '').localeCompare(server.appearance.updatedAt || '') > 0
      ? relay.appearance
      : server.appearance,
    cards: cards.map((card) => ({
      ...card,
      ...checklistCounts(checklistsByCardId[card.id] || []),
    })),
    checklistsByCardId,
    checklistsHydratedAt: [
      server.checklistsHydratedAt,
      relay.checklistsHydratedAt,
    ].filter(Boolean).sort().at(-1) || null,
    cachedAt: [server.cachedAt, relay.cachedAt].sort().at(-1) || server.cachedAt,
  };
}

export function replaceCreatedCard(
  snapshot: LocalBoardSnapshot,
  operations: LocalOperation[],
  tempId: string,
  serverCard: Card,
) {
  const existingChecklists = (snapshot.checklistsByCardId[tempId] || []).map((checklist) => ({
    ...checklist,
    cardId: serverCard.id,
  }));
  const nextChecklists = { ...snapshot.checklistsByCardId };
  delete nextChecklists[tempId];
  nextChecklists[serverCard.id] = existingChecklists;
  const nextSnapshot = {
    ...snapshot,
    cards: snapshot.cards.map((card) => card.id === tempId ? {
      ...serverCard,
      ...checklistCounts(existingChecklists),
    } : card),
    checklistsByCardId: nextChecklists,
    cachedAt: new Date().toISOString(),
  };
  const nextOperations = operations.map((operation) =>
    remapCardIdInOperation(operation, tempId, serverCard.id));

  return { snapshot: nextSnapshot, operations: nextOperations };
}

export function replaceCreatedChecklist(
  snapshot: LocalBoardSnapshot,
  operations: LocalOperation[],
  cardId: string,
  tempId: string,
  serverChecklist: Checklist,
) {
  const current = snapshot.checklistsByCardId[cardId] || [];
  const existingItems = current.find((checklist) => checklist.id === tempId)?.items || [];
  const checklist = {
    ...serverChecklist,
    items: existingItems.map((item) => ({ ...item, checklistId: serverChecklist.id })),
  };
  const nextSnapshot = withChecklists(
    snapshot,
    cardId,
    current.map((candidate) => candidate.id === tempId ? checklist : candidate),
    serverChecklist.updatedAt,
  );
  const nextOperations = operations.map((operation) => {
    if (operation.entityId === tempId) {
      return { ...operation, entityId: serverChecklist.id } as LocalOperation;
    }
    if (
      operation.kind === 'checklist.item.create'
      || operation.kind === 'checklist.item.update'
      || operation.kind === 'checklist.item.delete'
    ) {
      if (operation.payload.checklistId === tempId) {
        return {
          ...operation,
          payload: {
            ...operation.payload,
            checklistId: serverChecklist.id,
            ...('tempItem' in operation.payload
              ? {
                tempItem: {
                  ...operation.payload.tempItem,
                  checklistId: serverChecklist.id,
                },
              }
              : {}),
          },
        } as LocalOperation;
      }
    }
    return operation;
  });
  return { snapshot: nextSnapshot, operations: nextOperations };
}

export function replaceCreatedChecklistItem(
  snapshot: LocalBoardSnapshot,
  operations: LocalOperation[],
  cardId: string,
  tempId: string,
  serverItem: ChecklistItem,
) {
  const current = snapshot.checklistsByCardId[cardId] || [];
  const nextSnapshot = withChecklists(
    snapshot,
    cardId,
    current.map((checklist) => checklist.id === serverItem.checklistId
      ? {
        ...checklist,
        items: checklist.items.map((item) => item.id === tempId ? serverItem : item),
        updatedAt: serverItem.updatedAt,
      }
      : checklist),
    serverItem.updatedAt,
  );
  const nextOperations = operations.map((operation) => operation.entityId === tempId
    ? { ...operation, entityId: serverItem.id } as LocalOperation
    : operation);
  return { snapshot: nextSnapshot, operations: nextOperations };
}

export function createTemporaryCard(input: {
  id: string;
  boardId: string;
  columnId: string;
  title: string;
  description?: string;
  priority?: Card['priority'];
  cards: Card[];
  now: string;
}): Card {
  return {
    id: input.id,
    boardId: input.boardId,
    columnId: input.columnId,
    parentCardId: null,
    title: input.title,
    description: input.description || null,
    priority: input.priority ?? null,
    position: nextCardPosition(input.cards, input.columnId),
    startAt: null,
    dueAt: null,
    isArchived: false,
    labelIds: [],
    checklistCount: 0,
    checklistItemCount: 0,
    checklistCompletedItemCount: 0,
    commentCount: 0,
    createdByUserId: null,
    createdAt: input.now,
    updatedAt: input.now,
    archivedAt: null,
  };
}

export function createTemporaryChecklist(input: {
  id: string;
  cardId: string;
  title: string;
  checklists: Checklist[];
  now: string;
}): Checklist {
  return {
    id: input.id,
    cardId: input.cardId,
    title: input.title,
    position: nextPosition(input.checklists),
    items: [],
    createdAt: input.now,
    updatedAt: input.now,
  };
}

export function createTemporaryChecklistItem(input: {
  id: string;
  checklistId: string;
  title: string;
  items: ChecklistItem[];
  now: string;
}): ChecklistItem {
  return {
    id: input.id,
    checklistId: input.checklistId,
    title: input.title,
    isDone: false,
    position: nextPosition(input.items),
    completedAt: null,
    createdAt: input.now,
    updatedAt: input.now,
  };
}

export function isTemporaryCardId(id: string) {
  return id.startsWith('local-card-');
}

export function isTemporaryChecklistId(id: string) {
  return id.startsWith('local-checklist-');
}

export function isTemporaryChecklistItemId(id: string) {
  return id.startsWith('local-checklist-item-');
}
