import type {
  Board,
  BoardColumn,
  Card,
  Checklist,
  ChecklistItem,
} from '../../shared/types/api';
import {
  LOCAL_SCHEMA_VERSION,
  applyOperations,
  createTemporaryCard,
  createTemporaryChecklist,
  createTemporaryChecklistItem,
  mergeBoardSnapshots,
  replaceCreatedCard,
  replaceCreatedChecklist,
  replaceCreatedChecklistItem,
  type LocalBoardSnapshot,
  type LocalOperation,
} from './model';
import { defaultBoardAppearance } from '../appearance/boardTheme';

const board: Board = {
  id: 'board-1',
  workspaceId: 'workspace-1',
  name: 'Mobile',
  boardType: 'kanban',
  isArchived: false,
  createdAt: '2026-07-26T10:00:00Z',
  updatedAt: '2026-07-26T10:00:00Z',
};

const columnA: BoardColumn = {
  id: 'column-a',
  boardId: board.id,
  name: 'План',
  position: 1000,
  createdAt: board.createdAt,
  updatedAt: board.updatedAt,
};

const columnB: BoardColumn = {
  ...columnA,
  id: 'column-b',
  name: 'Готово',
  position: 2000,
};

function snapshot(cards: Card[] = []): LocalBoardSnapshot {
  return {
    schemaVersion: LOCAL_SCHEMA_VERSION,
    workspaceId: board.workspaceId,
    board,
    appearance: defaultBoardAppearance(board.id),
    columns: [columnA, columnB],
    cards,
    checklistsByCardId: {},
    checklistsHydratedAt: board.updatedAt,
    cachedAt: board.updatedAt,
    lastServerRefreshAt: board.updatedAt,
  };
}

describe('local-first reducer', () => {
  it('keeps a fresh relay checklist item when the coordinator snapshot is stale', () => {
    const localCard = createTemporaryCard({
      id: 'shared-card',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Сверка',
      cards: [],
      now: board.updatedAt,
    });
    const checklist = createTemporaryChecklist({
      id: 'shared-checklist',
      cardId: localCard.id,
      title: 'Пункты',
      checklists: [],
      now: board.updatedAt,
    });
    const first = createTemporaryChecklistItem({
      id: 'first-item',
      checklistId: checklist.id,
      title: 'Первый',
      items: [],
      now: board.updatedAt,
    });
    const second = createTemporaryChecklistItem({
      id: 'relay-item',
      checklistId: checklist.id,
      title: 'Только в relay',
      items: [first],
      now: '2026-07-26T10:05:00Z',
    });
    const server = snapshot([localCard]);
    server.checklistsByCardId[localCard.id] = [{ ...checklist, items: [first] }];
    const relay = snapshot([localCard]);
    relay.checklistsByCardId[localCard.id] = [{
      ...checklist,
      updatedAt: second.updatedAt,
      items: [first, second],
    }];

    const merged = mergeBoardSnapshots(server, relay);

    expect(merged.checklistsByCardId[localCard.id]?.[0]?.items.map((item) => item.id))
      .toEqual(['first-item', 'relay-item']);
    expect(merged.cards[0]?.checklistItemCount).toBe(2);
  });

  it('does not resurrect coordinator checklist data covered by relay tombstones', () => {
    const localCard = createTemporaryCard({
      id: 'tombstone-card',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Удаления',
      cards: [],
      now: board.updatedAt,
    });
    const checklist = createTemporaryChecklist({
      id: 'stale-checklist',
      cardId: localCard.id,
      title: 'Уже удалён',
      checklists: [],
      now: board.updatedAt,
    });
    const server = snapshot([localCard]);
    server.checklistsByCardId[localCard.id] = [{ ...checklist, items: [] }];
    const relay = snapshot([localCard]);

    const merged = mergeBoardSnapshots(server, relay, {
      checklistTombstones: { [checklist.id]: {} },
    });

    expect(merged.checklistsByCardId[localCard.id]).toEqual([]);
    expect(merged.cards[0]?.checklistCount).toBe(0);
  });

  it('replays create, update and move in their original order', () => {
    const temp = createTemporaryCard({
      id: 'local-card-one',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Первый APK',
      cards: [],
      now: '2026-07-26T10:01:00Z',
    });
    const operations: LocalOperation[] = [
      {
        id: 'op-1',
        boardId: board.id,
        entityId: temp.id,
        kind: 'card.create',
        status: 'pending',
        createdAt: temp.createdAt,
        attempts: 0,
        lastError: null,
        payload: {
          input: { title: temp.title, columnId: columnA.id },
          tempCard: temp,
        },
      },
      {
        id: 'op-2',
        boardId: board.id,
        entityId: temp.id,
        kind: 'card.update',
        status: 'pending',
        createdAt: '2026-07-26T10:02:00Z',
        attempts: 0,
        lastError: null,
        payload: { input: { priority: 'high' } },
      },
      {
        id: 'op-3',
        boardId: board.id,
        entityId: temp.id,
        kind: 'card.move',
        status: 'pending',
        createdAt: '2026-07-26T10:03:00Z',
        attempts: 0,
        lastError: null,
        payload: { input: { targetColumnId: columnB.id } },
      },
    ];

    const result = applyOperations(snapshot(), operations);
    expect(result.cards).toHaveLength(1);
    expect(result.cards[0]).toMatchObject({
      id: temp.id,
      priority: 'high',
      columnId: columnB.id,
    });
  });

  it('rewrites later operations after a temporary card receives a server id', () => {
    const temp = createTemporaryCard({
      id: 'local-card-one',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Первый APK',
      cards: [],
      now: '2026-07-26T10:01:00Z',
    });
    const serverCard: Card = { ...temp, id: 'server-card-1' };
    const operations: LocalOperation[] = [
      {
        id: 'op-1',
        boardId: board.id,
        entityId: temp.id,
        kind: 'card.create',
        status: 'pending',
        createdAt: temp.createdAt,
        attempts: 0,
        lastError: null,
        payload: {
          input: { title: temp.title, columnId: columnA.id },
          tempCard: temp,
        },
      },
      {
        id: 'op-2',
        boardId: board.id,
        entityId: temp.id,
        kind: 'card.update',
        status: 'pending',
        createdAt: temp.createdAt,
        attempts: 0,
        lastError: null,
        payload: { input: { title: 'После создания' } },
      },
    ];

    const result = replaceCreatedCard(snapshot([temp]), operations, temp.id, serverCard);
    expect(result.snapshot.cards[0]?.id).toBe(serverCard.id);
    expect(result.operations.every((operation) => operation.entityId === serverCard.id)).toBe(true);
  });

  it('toggles a checklist item in the local snapshot', () => {
    const localCard = createTemporaryCard({
      id: 'card-with-checklist',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Карточка с чек-листом',
      cards: [],
      now: board.updatedAt,
    });
    const initial = snapshot([localCard]);
    initial.checklistsByCardId[localCard.id] = [{
      id: 'checklist-1',
      cardId: localCard.id,
      title: 'Проверки',
      position: 1000,
      createdAt: board.createdAt,
      updatedAt: board.updatedAt,
      items: [{
        id: 'item-1',
        checklistId: 'checklist-1',
        title: 'Собрать APK',
        isDone: false,
        position: 1000,
        completedAt: null,
        createdAt: board.createdAt,
        updatedAt: board.updatedAt,
      }],
    }];
    const operation: LocalOperation = {
      id: 'op-checklist-1',
      boardId: board.id,
      entityId: 'item-1',
      kind: 'checklist.item.update',
      status: 'pending',
      createdAt: '2026-07-26T10:04:00Z',
      attempts: 0,
      lastError: null,
      payload: {
        cardId: localCard.id,
        checklistId: 'checklist-1',
        input: { isDone: true },
      },
    };

    const result = applyOperations(initial, [operation]);
    expect(result.checklistsByCardId[localCard.id]?.[0]?.items[0]?.isDone).toBe(true);
    expect(result.cards[0]).toMatchObject({
      checklistCount: 1,
      checklistItemCount: 1,
      checklistCompletedItemCount: 1,
    });
  });

  it('replays the complete checklist CRUD sequence and updates card counters', () => {
    const localCard = createTemporaryCard({
      id: 'card-checklist-crud',
      boardId: board.id,
      columnId: columnA.id,
      title: 'CRUD чек-листа',
      cards: [],
      now: board.updatedAt,
    });
    const checklist = createTemporaryChecklist({
      id: 'local-checklist-one',
      cardId: localCard.id,
      title: 'Первичное название',
      checklists: [],
      now: '2026-07-26T10:01:00Z',
    });
    const item = createTemporaryChecklistItem({
      id: 'local-checklist-item-one',
      checklistId: checklist.id,
      title: 'Первичный пункт',
      items: [],
      now: '2026-07-26T10:02:00Z',
    });
    const common = {
      boardId: board.id,
      status: 'pending' as const,
      attempts: 0,
      lastError: null,
    };
    const createAndUpdate: LocalOperation[] = [
      {
        ...common,
        id: 'op-create-checklist',
        entityId: checklist.id,
        kind: 'checklist.create',
        createdAt: checklist.createdAt,
        payload: {
          cardId: localCard.id,
          input: { title: checklist.title, position: checklist.position },
          tempChecklist: checklist,
        },
      },
      {
        ...common,
        id: 'op-update-checklist',
        entityId: checklist.id,
        kind: 'checklist.update',
        createdAt: '2026-07-26T10:01:30Z',
        payload: {
          cardId: localCard.id,
          input: { title: 'Проверки релиза' },
        },
      },
      {
        ...common,
        id: 'op-create-item',
        entityId: item.id,
        kind: 'checklist.item.create',
        createdAt: item.createdAt,
        payload: {
          cardId: localCard.id,
          checklistId: checklist.id,
          input: { title: item.title, position: item.position },
          tempItem: item,
        },
      },
      {
        ...common,
        id: 'op-update-item',
        entityId: item.id,
        kind: 'checklist.item.update',
        createdAt: '2026-07-26T10:03:00Z',
        payload: {
          cardId: localCard.id,
          checklistId: checklist.id,
          input: { title: 'Собрать APK', isDone: true },
        },
      },
    ];

    const populated = applyOperations(snapshot([localCard]), createAndUpdate);
    expect(populated.checklistsByCardId[localCard.id]?.[0]).toMatchObject({
      title: 'Проверки релиза',
      items: [{ title: 'Собрать APK', isDone: true }],
    });
    expect(populated.cards[0]).toMatchObject({
      checklistCount: 1,
      checklistItemCount: 1,
      checklistCompletedItemCount: 1,
    });

    const cleared = applyOperations(populated, [
      {
        ...common,
        id: 'op-delete-item',
        entityId: item.id,
        kind: 'checklist.item.delete',
        createdAt: '2026-07-26T10:04:00Z',
        payload: {
          cardId: localCard.id,
          checklistId: checklist.id,
        },
      },
      {
        ...common,
        id: 'op-delete-checklist',
        entityId: checklist.id,
        kind: 'checklist.delete',
        createdAt: '2026-07-26T10:05:00Z',
        payload: { cardId: localCard.id },
      },
    ]);
    expect(cleared.checklistsByCardId[localCard.id]).toEqual([]);
    expect(cleared.cards[0]).toMatchObject({
      checklistCount: 0,
      checklistItemCount: 0,
      checklistCompletedItemCount: 0,
    });
  });

  it('remaps temporary checklist and item ids after coordinator creation', () => {
    const localCard = createTemporaryCard({
      id: 'server-card',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Переназначение ID',
      cards: [],
      now: board.updatedAt,
    });
    const tempChecklist = createTemporaryChecklist({
      id: 'local-checklist-remap',
      cardId: localCard.id,
      title: 'Проверки',
      checklists: [],
      now: board.updatedAt,
    });
    const tempItem = createTemporaryChecklistItem({
      id: 'local-checklist-item-remap',
      checklistId: tempChecklist.id,
      title: 'Пункт',
      items: [],
      now: board.updatedAt,
    });
    const initial = snapshot([localCard]);
    initial.checklistsByCardId[localCard.id] = [{
      ...tempChecklist,
      items: [tempItem],
    }];
    const operations: LocalOperation[] = [
      {
        id: 'op-checklist-create',
        boardId: board.id,
        entityId: tempChecklist.id,
        kind: 'checklist.create',
        status: 'pending',
        createdAt: board.updatedAt,
        attempts: 0,
        lastError: null,
        payload: {
          cardId: localCard.id,
          input: { title: tempChecklist.title },
          tempChecklist,
        },
      },
      {
        id: 'op-item-create',
        boardId: board.id,
        entityId: tempItem.id,
        kind: 'checklist.item.create',
        status: 'pending',
        createdAt: board.updatedAt,
        attempts: 0,
        lastError: null,
        payload: {
          cardId: localCard.id,
          checklistId: tempChecklist.id,
          input: { title: tempItem.title },
          tempItem,
        },
      },
      {
        id: 'op-item-update',
        boardId: board.id,
        entityId: tempItem.id,
        kind: 'checklist.item.update',
        status: 'pending',
        createdAt: board.updatedAt,
        attempts: 0,
        lastError: null,
        payload: {
          cardId: localCard.id,
          checklistId: tempChecklist.id,
          input: { isDone: true },
        },
      },
    ];
    const serverChecklist: Checklist = {
      ...tempChecklist,
      id: 'server-checklist',
      items: [],
    };
    const checklistResult = replaceCreatedChecklist(
      initial,
      operations,
      localCard.id,
      tempChecklist.id,
      serverChecklist,
    );
    expect(checklistResult.snapshot.checklistsByCardId[localCard.id]?.[0]?.id)
      .toBe(serverChecklist.id);
    expect(checklistResult.operations
      .every((operation) => {
        if (
          operation.kind !== 'checklist.item.create'
          && operation.kind !== 'checklist.item.update'
          && operation.kind !== 'checklist.item.delete'
        ) return true;
        return operation.payload.checklistId === serverChecklist.id;
      })).toBe(true);

    const serverItem: ChecklistItem = {
      ...tempItem,
      id: 'server-item',
      checklistId: serverChecklist.id,
    };
    const itemResult = replaceCreatedChecklistItem(
      checklistResult.snapshot,
      checklistResult.operations,
      localCard.id,
      tempItem.id,
      serverItem,
    );
    expect(itemResult.snapshot.checklistsByCardId[localCard.id]?.[0]?.items[0]?.id)
      .toBe(serverItem.id);
    expect(itemResult.operations
      .filter((operation) => operation.entityId === serverItem.id)).toHaveLength(2);
  });

  it('removes a card and its checklists for an optimistic global delete', () => {
    const existing = createTemporaryCard({
      id: 'server-card-delete',
      boardId: board.id,
      columnId: columnA.id,
      title: 'Удалить везде',
      cards: [],
      now: board.updatedAt,
    });
    const initial = {
      ...snapshot([existing]),
      checklistsByCardId: { [existing.id]: [] },
    };
    const result = applyOperations(initial, [{
      id: 'op-delete-card',
      boardId: board.id,
      entityId: existing.id,
      kind: 'card.delete',
      status: 'pending',
      createdAt: '2026-07-26T10:10:00Z',
      attempts: 0,
      lastError: null,
      payload: { card: existing },
    }]);
    expect(result.cards).toEqual([]);
    expect(result.checklistsByCardId[existing.id]).toBeUndefined();
  });
});
