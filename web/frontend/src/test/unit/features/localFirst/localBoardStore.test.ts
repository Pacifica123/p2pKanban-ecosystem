import { beforeEach, describe, expect, it } from 'vitest';
import {
  enqueueCreateCardOperation,
  enqueueUpdateCardOperation,
  getLocalFirstEntityKey,
  getLocalFirstOperationsForBoard,
  loadLocalBoardSnapshot,
  markFailedOperationsForRetry,
  markLocalFirstOperationStatus,
  seedLocalBoardSnapshotFromServer,
} from '@/features/localFirst/lib/localBoardStore';
import type { Board, BoardColumn, Card } from '@/shared/types/api';

const board: Board = {
  id: 'board-1',
  workspaceId: 'workspace-1',
  name: 'Local-first board',
  description: null,
  boardType: 'kanban',
  isArchived: false,
  createdAt: '2026-05-18T00:00:00.000Z',
  updatedAt: '2026-05-18T00:00:00.000Z',
  archivedAt: null,
};

const column: BoardColumn = {
  id: 'column-1',
  boardId: board.id,
  name: 'Todo',
  description: null,
  position: 1000,
  colorToken: null,
  wipLimit: null,
  createdAt: board.createdAt,
  updatedAt: board.updatedAt,
};

const card: Card = {
  id: 'card-1',
  boardId: board.id,
  columnId: column.id,
  parentCardId: null,
  title: 'Seed card',
  description: null,
  priority: null,
  position: 1000,
  startAt: null,
  dueAt: null,
  isArchived: false,
  labelIds: [],
  checklistCount: 0,
  checklistCompletedItemCount: 0,
  commentCount: 0,
  createdByUserId: null,
  createdAt: board.createdAt,
  updatedAt: board.updatedAt,
  archivedAt: null,
};

describe('localBoardStore', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('persists server board snapshot and local card create operation', () => {
    seedLocalBoardSnapshotFromServer({ workspaceId: board.workspaceId, board, columns: [column], cards: [card] });

    const created = enqueueCreateCardOperation(board.id, { title: 'Offline card', columnId: column.id });
    const snapshot = loadLocalBoardSnapshot(board.id);
    const operations = getLocalFirstOperationsForBoard(board.id);

    expect(snapshot?.cards.some((item) => item.id === created.id && item.title === 'Offline card')).toBe(true);
    expect(operations).toHaveLength(1);
    expect(snapshot?.syncMetadata[getLocalFirstEntityKey('card', created.id)]?.status).toBe('pending');
  });

  it('tracks failed operation status and can mark it retryable again', () => {
    seedLocalBoardSnapshotFromServer({ workspaceId: board.workspaceId, board, columns: [column], cards: [card] });
    enqueueUpdateCardOperation(board.id, card.id, { title: 'Edited offline' });

    const [operation] = getLocalFirstOperationsForBoard(board.id);
    markLocalFirstOperationStatus(operation.id, 'failed', 'Backend unavailable');

    expect(loadLocalBoardSnapshot(board.id)?.syncMetadata[getLocalFirstEntityKey('card', card.id)]?.status).toBe('failed');

    markFailedOperationsForRetry(board.id);

    expect(loadLocalBoardSnapshot(board.id)?.syncMetadata[getLocalFirstEntityKey('card', card.id)]?.status).toBe('pending');
  });
});
