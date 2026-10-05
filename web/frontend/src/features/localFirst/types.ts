import type { Board, BoardColumn, Card, CardPriority, Workspace } from '@/shared/types/api';

export const LOCAL_FIRST_SCHEMA_VERSION = 2;

export type LocalSyncStatus = 'synced' | 'pending' | 'failed';
export type LocalEntityKind = 'workspace' | 'board' | 'column' | 'card';
export type LocalFirstOperationStatus = 'pending' | 'failed';

export interface LocalEntitySyncMetadata {
  status: LocalSyncStatus;
  operationIds: string[];
  updatedAt: string;
  error?: string | null;
}

export interface LocalWorkspaceSchema {
  id: string;
  value?: Workspace | null;
  cachedAt: string;
}

export interface LocalBoardSnapshot {
  schemaVersion: typeof LOCAL_FIRST_SCHEMA_VERSION;
  workspace: LocalWorkspaceSchema;
  board?: Board | null;
  columns: BoardColumn[];
  cards: Card[];
  cachedAt: string;
  lastServerRefreshAt?: string | null;
  syncMetadata: Record<string, LocalEntitySyncMetadata>;
}

export interface LocalCreateCardInput {
  title: string;
  description?: string | null;
  columnId: string;
  priority?: CardPriority;
}

export interface LocalUpdateCardInput {
  title?: string;
  description?: string | null;
  priority?: CardPriority;
  dueAt?: string | null;
}

export interface LocalMoveCardInput {
  targetColumnId: string;
  position?: number | null;
}

export interface LocalReorderColumnCardsInput {
  items: Array<{
    cardId: string;
    position: number;
  }>;
}

export interface LocalFirstOperationBase<TKind extends string, TPayload> {
  id: string;
  boardId: string;
  entityKind: LocalEntityKind;
  entityId: string;
  kind: TKind;
  status: LocalFirstOperationStatus;
  payload: TPayload;
  createdAt: string;
  updatedAt: string;
  attempts: number;
  lastError?: string | null;
}

export type LocalFirstOperation =
  | LocalFirstOperationBase<'card.create', { input: LocalCreateCardInput; tempCard: Card }>
  | LocalFirstOperationBase<'card.update', { input: LocalUpdateCardInput }>
  | LocalFirstOperationBase<'card.move', { input: LocalMoveCardInput }>
  | LocalFirstOperationBase<'column.cards.reorder', { input: LocalReorderColumnCardsInput }>;

export interface LocalFirstBoardRuntime {
  boardId?: string;
  workspaceId?: string;
  snapshot: LocalBoardSnapshot | null;
  board?: Board | null;
  columns: BoardColumn[];
  cards: Card[];
  isOnline: boolean;
  hasWarmSnapshot: boolean;
  pendingCount: number;
  failedCount: number;
  isFlushing: boolean;
  lastError?: string | null;
  enqueueCreateCard: (input: LocalCreateCardInput) => Card;
  enqueueUpdateCard: (cardId: string, input: LocalUpdateCardInput) => void;
  enqueueMoveCard: (cardId: string, input: LocalMoveCardInput) => void;
  enqueueReorderColumnCards: (columnId: string, input: LocalReorderColumnCardsInput) => void;
  flushPendingOperations: () => Promise<void>;
  retryFailedOperations: () => Promise<void>;
  getEntityStatus: (kind: LocalEntityKind, entityId: string) => LocalEntitySyncMetadata | null;
}
