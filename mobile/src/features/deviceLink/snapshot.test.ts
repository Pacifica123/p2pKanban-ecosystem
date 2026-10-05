import { overlayBoard } from './snapshot';
import { orderCards } from '../../shared/lib/cardOrder';
import { getAdjacentPosition } from '../boards/cardDrag';
const card = (
  id: string,
  position: number,
  priority: string | null = null,
) => ({
  id,
  position,
  priority,
  columnId: 'col',
  boardId: 'b',
  title: id,
  isArchived: false,
});
test('partial cache does not delete unseen cards; explicit deletion prunes dependent rows', () => {
  const payload: any = {
    columns: [{ id: 'col', boardId: 'b' }],
    cards: [card('hidden', 1), card('deleted', 2), card('edited', 3)],
    checklists: [{ id: 'list', cardId: 'deleted' }],
    checklistItems: [{ id: 'item', checklistId: 'list' }],
    cardLabels: [{ cardId: 'deleted' }],
    comments: [{ cardId: 'deleted' }],
    boardAppearanceSettings: [],
  };
  const local: any = {
    board: { id: 'b' },
    cards: [{ ...card('edited', 3), title: 'Offline' }],
    checklistsHydratedAt: null,
    checklistsByCardId: {},
    appearance: {},
  };
  overlayBoard(payload, local, new Set(['deleted']));
  expect(payload.cards.map((c: any) => c.id)).toEqual(['hidden', 'edited']);
  expect(payload.cards[1].title).toBe('Offline');
  expect(payload.checklistItems).toEqual([]);
  expect(payload.comments).toEqual([]);
  local.columns = [{ id: 'new-column', boardId: 'b' }];
  local.cards[0].columnId = 'new-column';
  overlayBoard(payload, local, new Set());
  expect(payload.boards.map((board: any) => board.id)).toEqual(['b']);
  expect(payload.columns.map((column: any) => column.id)).toContain('new-column');
});
test('adjacent move works without changing priority/manual order', () => {
  const cards: any = [
    card('a', 1024, 'low'),
    card('b', 2048, 'urgent'),
    card('c', 3072, 'urgent'),
  ];
  expect(getAdjacentPosition(cards, 'a', -1)).toBeNull();
  expect(getAdjacentPosition(cards, 'c', 1)).toBeNull();
  const moved = cards.map((c: any) =>
    c.id === 'a' ? { ...c, position: getAdjacentPosition(cards, 'a', 1)! } : c,
  );
  expect(orderCards(moved, false).map((c) => c.id)).toEqual(['b', 'a', 'c']);
  expect(orderCards(cards, true).map((c) => c.id)).toEqual(['b', 'c', 'a']);
  expect(orderCards(cards, false).map((c) => c.id)).toEqual(['a', 'b', 'c']);
});
