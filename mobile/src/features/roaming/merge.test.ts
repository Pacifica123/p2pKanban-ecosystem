import type { Card } from '../../shared/types/api';
import { LOCAL_SCHEMA_VERSION, type LocalBoardSnapshot } from '../localFirst/model';
import { applyRoamingEvents, EMPTY_ROAMING_APPLY_STATE } from './merge';
import { ROAMING_PROTOCOL_VERSION, type RoamingBoardEvent } from './types';
import { defaultBoardAppearance } from '../appearance/boardTheme';

const workspaceId = '018f22e2-355a-7ba2-8ef0-d7bc788ceec8';
const boardId = '018f22e2-355a-7ba2-8ef0-d7bc788ceec9';
const cardId = '018f22e2-355a-7ba2-8ef0-d7bc788ceeca';

function card(title: string): Card {
  return {
    id: cardId,
    boardId,
    columnId: '018f22e2-355a-7ba2-8ef0-d7bc788ceecb',
    title,
    priority: null,
    position: 1000,
    isArchived: false,
    createdAt: '2026-07-28T10:00:00.000Z',
    updatedAt: '2026-07-28T10:00:00.000Z',
  };
}

function snapshot(): LocalBoardSnapshot {
  return {
    schemaVersion: LOCAL_SCHEMA_VERSION,
    workspaceId,
    board: {
      id: boardId,
      workspaceId,
      name: 'Доска',
      boardType: 'kanban',
      isArchived: false,
      createdAt: '2026-07-28T10:00:00.000Z',
      updatedAt: '2026-07-28T10:00:00.000Z',
    },
    appearance: defaultBoardAppearance(boardId),
    columns: [],
    cards: [card('исходная')],
    checklistsByCardId: {},
    checklistsHydratedAt: '2026-07-28T10:00:00.000Z',
    cachedAt: '2026-07-28T10:00:00.000Z',
    lastServerRefreshAt: null,
  };
}

function event(logicalClock: number, replicaId: string, title: string): RoamingBoardEvent {
  return {
    protocolVersion: ROAMING_PROTOCOL_VERSION,
    eventId: `018f22e2-1d58-7f08-9a36-${replicaId.endsWith('b') ? '1' : '0'}${String(logicalClock).padStart(11, '0')}`,
    workspaceId,
    boardId,
    capabilityEpoch: 1,
    replicaId,
    replicaSeq: logicalClock,
    logicalClock,
    entityType: 'card',
    entityId: cardId,
    operation: 'card.put',
    fieldMask: ['title'],
    payload: { card: card(title) },
    occurredAt: '2026-07-28T12:00:00.000Z',
  };
}

test('later logical clock wins regardless of delivery order', () => {
  const result = applyRoamingEvents(snapshot(), EMPTY_ROAMING_APPLY_STATE, [
    event(9, 'replica-a', 'новее'),
    event(8, 'replica-z', 'старее'),
  ]);
  expect(result.snapshot?.cards[0]?.title).toBe('новее');
});

test('replica id deterministically resolves parallel events', () => {
  const result = applyRoamingEvents(snapshot(), EMPTY_ROAMING_APPLY_STATE, [
    event(9, 'replica-a', 'A'),
    event(9, 'replica-b', 'B'),
  ]);
  expect(result.snapshot?.cards[0]?.title).toBe('B');
});

test('board appearance events update the existing mobile snapshot', () => {
  const base = snapshot();
  const appearance = {
    ...defaultBoardAppearance(boardId),
    isCustomized: true,
    customProperties: { accentColor: '#e11d48' },
    wallpaper: { kind: 'image' as const, value: 'https://example.org/board.webp' },
    updatedAt: '2026-07-28T12:00:00.000Z',
  };
  const appearanceEvent: RoamingBoardEvent = {
    ...event(11, 'replica-a', 'исходная'),
    entityType: 'board',
    entityId: boardId,
    operation: 'board.appearance.put',
    fieldMask: ['appearance'],
    payload: { appearance },
  };

  const result = applyRoamingEvents(base, EMPTY_ROAMING_APPLY_STATE, [appearanceEvent]);

  expect(result.snapshot?.appearance).toEqual(appearance);
  expect(result.applied).toBe(1);
});

test('roaming card bundle carries checklist items', () => {
  const checklistEvent = event(10, 'replica-a', 'исходная');
  checklistEvent.fieldMask = ['checklists'];
  checklistEvent.payload = {
    card: card('исходная'),
    checklists: [{
      id: '018f22e2-355a-7ba2-8ef0-d7bc788ceecd',
      cardId,
      title: 'Релиз',
      position: 1000,
      createdAt: '2026-07-28T10:00:00.000Z',
      updatedAt: '2026-07-28T12:00:00.000Z',
      items: [{
        id: '018f22e2-355a-7ba2-8ef0-d7bc788ceece',
        checklistId: '018f22e2-355a-7ba2-8ef0-d7bc788ceecd',
        title: 'Проверить APK',
        isDone: true,
        position: 1000,
        completedAt: '2026-07-28T12:00:00.000Z',
        createdAt: '2026-07-28T10:00:00.000Z',
        updatedAt: '2026-07-28T12:00:00.000Z',
      }],
    }],
  };

  const result = applyRoamingEvents(
    snapshot(),
    EMPTY_ROAMING_APPLY_STATE,
    [checklistEvent],
  );
  expect(result.snapshot?.checklistsByCardId[cardId]?.[0]?.items[0]?.isDone).toBe(true);
});

test('legacy stale snapshot cannot delete a checklist item that it does not contain', () => {
  const checklistId = '018f22e2-355a-7ba2-8ef0-d7bc788ceecd';
  const first = event(10, 'replica-a', 'исходная');
  first.fieldMask = ['checklists'];
  first.payload = {
    card: card('исходная'),
    checklists: [{
      id: checklistId,
      cardId,
      title: 'Релиз',
      position: 1000,
      createdAt: first.occurredAt,
      updatedAt: first.occurredAt,
      items: [{
        id: '018f22e2-355a-7ba2-8ef0-d7bc788ceece',
        checklistId,
        title: 'Первый',
        isDone: false,
        position: 1000,
        createdAt: first.occurredAt,
        updatedAt: first.occurredAt,
      }, {
        id: '018f22e2-355a-7ba2-8ef0-d7bc788ceecf',
        checklistId,
        title: 'Второй',
        isDone: false,
        position: 2000,
        createdAt: first.occurredAt,
        updatedAt: first.occurredAt,
      }],
    }],
  };
  const stale = event(11, 'replica-b', 'исходная');
  stale.fieldMask = ['checklists'];
  stale.payload = {
    card: card('исходная'),
    checklists: [{
      id: checklistId,
      cardId,
      title: 'Релиз',
      position: 1000,
      createdAt: first.occurredAt,
      updatedAt: stale.occurredAt,
      items: [{
        id: '018f22e2-355a-7ba2-8ef0-d7bc788ceece',
        checklistId,
        title: 'Устаревшее название',
        isDone: true,
        position: 1000,
        createdAt: first.occurredAt,
        updatedAt: stale.occurredAt,
      }],
    }],
  };

  const seeded = applyRoamingEvents(snapshot(), EMPTY_ROAMING_APPLY_STATE, [first]);
  const result = applyRoamingEvents(seeded.snapshot, seeded.state, [stale]);
  const items = result.snapshot?.checklistsByCardId[cardId]?.[0]?.items;
  expect(items).toHaveLength(2);
  expect(items?.[0]?.title).toBe('Первый');
  expect(items?.[0]?.isDone).toBe(false);
});

test('checklist item deltas merge independently and explicit delete wins', () => {
  const checklistId = '018f22e2-355a-7ba2-8ef0-d7bc788ceecd';
  const checklistCreate = event(10, 'replica-a', 'исходная');
  checklistCreate.fieldMask = ['checklists'];
  checklistCreate.payload = {
    card: card('исходная'),
    checklistDelta: {
      kind: 'checklist.put',
      cardId,
      checklistId,
      fieldMask: ['*'],
      checklist: {
        id: checklistId,
        cardId,
        title: 'Релиз',
        position: 1000,
        items: [],
        createdAt: checklistCreate.occurredAt,
        updatedAt: checklistCreate.occurredAt,
      },
    },
  };
  const itemId = '018f22e2-355a-7ba2-8ef0-d7bc788ceece';
  const itemCreate = event(11, 'replica-b', 'исходная');
  itemCreate.fieldMask = ['checklists'];
  itemCreate.payload = {
    card: card('исходная'),
    checklistDelta: {
      kind: 'checklist_item.put',
      cardId,
      checklistId,
      itemId,
      fieldMask: ['*'],
      item: {
        id: itemId,
        checklistId,
        title: 'Первый',
        isDone: false,
        position: 1000,
        createdAt: itemCreate.occurredAt,
        updatedAt: itemCreate.occurredAt,
      },
    },
  };
  const itemDelete = event(12, 'replica-a', 'исходная');
  itemDelete.fieldMask = ['checklists'];
  itemDelete.payload = {
    card: card('исходная'),
    checklistDelta: {
      kind: 'checklist_item.delete',
      cardId,
      checklistId,
      itemId,
      fieldMask: ['__lifecycle'],
      deletedAt: itemDelete.occurredAt,
    },
  };

  const result = applyRoamingEvents(snapshot(), EMPTY_ROAMING_APPLY_STATE, [
    checklistCreate,
    itemCreate,
    itemDelete,
  ]);
  expect(result.snapshot?.checklistsByCardId[cardId]?.[0]?.items).toEqual([]);
  expect(result.state.checklistItemTombstones[itemId]).toBeDefined();
});

test('card tombstone wins over later stale card.put and prevents resurrection', () => {
  const deleted = event(10, 'replica-a', 'удалена');
  deleted.operation = 'card.delete';
  deleted.fieldMask = ['__lifecycle'];
  deleted.payload = { deletedAt: '2026-07-28T12:00:00.000Z' };
  const stalePut = event(99, 'replica-z', 'не должна воскреснуть');

  const first = applyRoamingEvents(
    snapshot(),
    EMPTY_ROAMING_APPLY_STATE,
    [deleted],
  );
  expect(first.snapshot?.cards).toEqual([]);
  expect(first.state.tombstones[cardId]).toBeDefined();

  const second = applyRoamingEvents(first.snapshot, first.state, [stalePut]);
  expect(second.snapshot?.cards).toEqual([]);
  expect(second.applied).toBe(0);
});

test('versioned web snapshot repairs cached checklist fields without HTTP or old deltas', () => {
  const base=snapshot();
  const checklist={id:'checklist',cardId,title:'List',position:1,createdAt:base.cachedAt,updatedAt:base.cachedAt,
    items:[{id:'item',checklistId:'checklist',title:'Item',position:1,isDone:false,createdAt:base.cachedAt,updatedAt:base.cachedAt}]};
  base.checklistsByCardId[cardId]=[checklist];
  const remote={...base,checklistsByCardId:{[cardId]:[{...checklist,items:[{...checklist.items[0]!,isDone:true}]}]}};
  const stamp={logicalClock:20,replicaId:'replica-b',eventId:'stamp'};
  const recovery:RoamingBoardEvent={...event(1,'replica-b','same'),entityType:'board',entityId:boardId,
    operation:'board.snapshot',payload:{snapshot:remote,fieldVersions:{'item:checklist_item.isDone':stamp}}};
  const result=applyRoamingEvents(base,EMPTY_ROAMING_APPLY_STATE,[recovery]);
  expect(result.snapshot?.checklistsByCardId[cardId]?.[0]?.items[0]?.isDone).toBe(true);
  const stale={...recovery,eventId:'stale',payload:{snapshot:base,fieldVersions:{'item:checklist_item.isDone':{...stamp,logicalClock:10}}}};
  const again=applyRoamingEvents(result.snapshot,result.state,[stale]);
  expect(again.snapshot?.checklistsByCardId[cardId]?.[0]?.items[0]?.isDone).toBe(true);
});

test('versioned recovery applies item tombstones to cached checklists',()=>{
 const base=snapshot();base.checklistsByCardId[cardId]=[{id:'list',cardId,title:'List',position:1,createdAt:base.cachedAt,updatedAt:base.cachedAt,
 items:[{id:'item',checklistId:'list',title:'Item',position:1,isDone:false,createdAt:base.cachedAt,updatedAt:base.cachedAt}]}];
 const remote={...base,checklistsByCardId:{[cardId]:[{...base.checklistsByCardId[cardId]![0]!,items:[]}]}};
 const recovery:RoamingBoardEvent={...event(1,'replica-b','same'),entityType:'board',entityId:boardId,operation:'board.snapshot',
 payload:{snapshot:remote,fieldVersions:{'item:checklist_item.__lifecycle':{logicalClock:30,replicaId:'replica-b',eventId:'delete'}}}};
 expect(applyRoamingEvents(base,EMPTY_ROAMING_APPLY_STATE,[recovery]).snapshot?.checklistsByCardId[cardId]?.[0]?.items).toEqual([]);
});
