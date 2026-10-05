import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createCard, moveCard, reorderColumnCards, updateCard } from '@/features/cards/api/cards';
import {
  enqueueCreateCardOperation,
  enqueueMoveCardOperation,
  enqueueReorderColumnCardsOperation,
  enqueueUpdateCardOperation,
  getLocalFirstEntityKey,
  getLocalFirstOperationsForBoard,
  isLocalCardId,
  loadLocalBoardSnapshot,
  markFailedOperationsForRetry,
  markLocalFirstOperationStatus,
  removeLocalFirstOperation,
  replaceLocalCardAfterCreate,
  seedLocalBoardSnapshotFromServer,
  subscribeLocalFirstStore,
} from '@/features/localFirst/lib/localBoardStore';
import type {
  LocalBoardSnapshot,
  LocalCreateCardInput,
  LocalEntityKind,
  LocalFirstBoardRuntime,
  LocalFirstOperation,
  LocalMoveCardInput,
  LocalReorderColumnCardsInput,
  LocalUpdateCardInput,
} from '@/features/localFirst/types';
import type { Board, BoardColumn, Card } from '@/shared/types/api';

interface UseLocalFirstBoardRuntimeInput {
  workspaceId?: string;
  boardId?: string;
  board?: Board | null;
  columns?: BoardColumn[] | null;
  cards?: Card[] | null;
  onRemoteFlush?: () => void | Promise<void>;
}

interface LocalFirstBoardState {
  snapshot: LocalBoardSnapshot | null;
  operations: LocalFirstOperation[];
}

function readState(boardId?: string): LocalFirstBoardState {
  return {
    snapshot: loadLocalBoardSnapshot(boardId),
    operations: getLocalFirstOperationsForBoard(boardId),
  };
}

function useOnlineState() {
  const [isOnline, setIsOnline] = useState(() => (typeof navigator === 'undefined' ? true : navigator.onLine));

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true);
    }

    function handleOffline() {
      setIsOnline(false);
    }

    if (typeof window === 'undefined') return undefined;
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  return isOnline;
}

function getOperationError(error: unknown) {
  return error instanceof Error ? error.message : 'Local-first operation failed';
}

function isNetworkUnavailableError(error: unknown) {
  return error instanceof Error && /network|failed to fetch|backend|fetch/i.test(error.message);
}

function resolveOperationIds(operation: LocalFirstOperation, cardIdMap: Map<string, string>): LocalFirstOperation {
  const resolvedEntityId = cardIdMap.get(operation.entityId) || operation.entityId;

  if (operation.kind === 'column.cards.reorder') {
    return {
      ...operation,
      entityId: resolvedEntityId,
      payload: {
        input: {
          items: operation.payload.input.items.map((item) => ({
            ...item,
            cardId: cardIdMap.get(item.cardId) || item.cardId,
          })),
        },
      },
    };
  }

  return {
    ...operation,
    entityId: resolvedEntityId,
  };
}

export function useLocalFirstBoardRuntime({
  workspaceId,
  boardId,
  board,
  columns,
  cards,
  onRemoteFlush,
}: UseLocalFirstBoardRuntimeInput): LocalFirstBoardRuntime {
  const isOnline = useOnlineState();
  const [state, setState] = useState<LocalFirstBoardState>(() => readState(boardId));
  const [isFlushing, setIsFlushing] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const flushLockRef = useRef(false);
  const onRemoteFlushRef = useRef(onRemoteFlush);

  onRemoteFlushRef.current = onRemoteFlush;

  useEffect(() => {
    setState(readState(boardId));
    return subscribeLocalFirstStore(() => setState(readState(boardId)));
  }, [boardId]);

  useEffect(() => {
    if (!workspaceId || !board || !columns || !cards) return;
    seedLocalBoardSnapshotFromServer({ workspaceId, board, columns, cards });
  }, [workspaceId, board, columns, cards]);

  const flushPendingOperations = useCallback(async () => {
    if (!boardId || flushLockRef.current) return;
    if (typeof navigator !== 'undefined' && !navigator.onLine) return;

    flushLockRef.current = true;
    setIsFlushing(true);
    setLastError(null);

    const cardIdMap = new Map<string, string>();

    try {
      const operations = getLocalFirstOperationsForBoard(boardId).filter((operation) => operation.status === 'pending');

      for (const pendingOperation of operations) {
        const operation = resolveOperationIds(pendingOperation, cardIdMap);

        try {
          if (operation.kind === 'card.create') {
            const createdCard = await createCard(operation.boardId, {
              ...operation.payload.input,
              description: operation.payload.input.description ?? undefined,
            });
            cardIdMap.set(operation.entityId, createdCard.id);
            replaceLocalCardAfterCreate(operation.boardId, operation.entityId, createdCard);
            removeLocalFirstOperation(operation.id);
          } else if (operation.kind === 'card.update') {
            if (isLocalCardId(operation.entityId)) {
              throw new Error('Cannot update a local card before its create operation is flushed.');
            }
            await updateCard(operation.entityId, operation.payload.input);
            removeLocalFirstOperation(operation.id);
          } else if (operation.kind === 'card.move') {
            if (isLocalCardId(operation.entityId)) {
              throw new Error('Cannot move a local card before its create operation is flushed.');
            }
            await moveCard(operation.entityId, operation.payload.input);
            removeLocalFirstOperation(operation.id);
          } else if (operation.kind === 'column.cards.reorder') {
            const unresolvedLocalItem = operation.payload.input.items.find((item) => isLocalCardId(item.cardId));
            if (unresolvedLocalItem) {
              throw new Error('Cannot reorder a local card before its create operation is flushed.');
            }
            await reorderColumnCards(operation.entityId, operation.payload.input);
            removeLocalFirstOperation(operation.id);
          }
        } catch (error) {
          const message = getOperationError(error);
          markLocalFirstOperationStatus(operation.id, 'failed', message);
          setLastError(message);
          if (isNetworkUnavailableError(error)) break;
        }
      }

      if (onRemoteFlushRef.current) {
        await onRemoteFlushRef.current();
      }
    } finally {
      flushLockRef.current = false;
      setIsFlushing(false);
      setState(readState(boardId));
    }
  }, [boardId]);

  useEffect(() => {
    if (!isOnline || !boardId) return;
    const hasPending = getLocalFirstOperationsForBoard(boardId).some((operation) => operation.status === 'pending');
    if (hasPending) {
      void flushPendingOperations();
    }
  }, [boardId, flushPendingOperations, isOnline, state.operations]);

  const retryFailedOperations = useCallback(async () => {
    if (!boardId) return;
    markFailedOperationsForRetry(boardId);
    await flushPendingOperations();
  }, [boardId, flushPendingOperations]);

  const enqueueCreateCard = useCallback((input: LocalCreateCardInput) => {
    if (!boardId) throw new Error('Board is required for local card create.');
    const created = enqueueCreateCardOperation(boardId, input);
    if (isOnline) void flushPendingOperations();
    return created;
  }, [boardId, flushPendingOperations, isOnline]);

  const enqueueUpdateCard = useCallback((cardId: string, input: LocalUpdateCardInput) => {
    if (!boardId) throw new Error('Board is required for local card update.');
    enqueueUpdateCardOperation(boardId, cardId, input);
    if (isOnline) void flushPendingOperations();
  }, [boardId, flushPendingOperations, isOnline]);

  const enqueueMoveCard = useCallback((cardId: string, input: LocalMoveCardInput) => {
    if (!boardId) throw new Error('Board is required for local card move.');
    enqueueMoveCardOperation(boardId, cardId, input);
    if (isOnline) void flushPendingOperations();
  }, [boardId, flushPendingOperations, isOnline]);

  const enqueueReorderColumnCards = useCallback((columnId: string, input: LocalReorderColumnCardsInput) => {
    if (!boardId) throw new Error('Board is required for local card reorder.');
    enqueueReorderColumnCardsOperation(boardId, columnId, input);
    if (isOnline) void flushPendingOperations();
  }, [boardId, flushPendingOperations, isOnline]);

  const pendingCount = useMemo(() => state.operations.filter((operation) => operation.status === 'pending').length, [state.operations]);
  const failedCount = useMemo(() => state.operations.filter((operation) => operation.status === 'failed').length, [state.operations]);
  const hasServerData = Boolean(board && columns && cards);

  const runtimeBoard = state.snapshot?.board ?? board ?? null;
  const runtimeColumns = state.snapshot?.columns ?? columns ?? [];
  const runtimeCards = state.snapshot?.cards ?? cards ?? [];

  return {
    boardId,
    workspaceId,
    snapshot: state.snapshot,
    board: runtimeBoard,
    columns: runtimeColumns,
    cards: runtimeCards,
    isOnline,
    hasWarmSnapshot: Boolean(state.snapshot) && !hasServerData,
    pendingCount,
    failedCount,
    isFlushing,
    lastError,
    enqueueCreateCard,
    enqueueUpdateCard,
    enqueueMoveCard,
    enqueueReorderColumnCards,
    flushPendingOperations,
    retryFailedOperations,
    getEntityStatus: (kind: LocalEntityKind, entityId: string) => {
      const key = getLocalFirstEntityKey(kind, entityId);
      return state.snapshot?.syncMetadata[key] ?? null;
    },
  };
}
