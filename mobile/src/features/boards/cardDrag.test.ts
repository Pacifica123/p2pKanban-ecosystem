import type { Card } from '../../shared/types/api';
import {
  getAppendPosition,
  getDropColumnIndex,
  getEdgeScrollOffset,
  moveCardPreview,
} from './cardDrag';

const card = (id: string, columnId: string, position: number): Card => ({
  id,
  boardId: 'board',
  columnId,
  title: id,
  priority: null,
  position,
  isArchived: false,
  createdAt: '2026-07-29T00:00:00.000Z',
  updatedAt: '2026-07-29T00:00:00.000Z',
});

test('drop column follows the horizontally scrolled page', () => {
  expect(getDropColumnIndex({
    scrollOffset: 337,
    pointerX: 180,
    contentInset: 16,
    columnWidth: 327,
    gap: 10,
    columnCount: 3,
  })).toBe(1);
});

test('edge scrolling moves exactly one column at a time', () => {
  expect(getEdgeScrollOffset({
    scrollOffset: 337,
    pointerX: 370,
    viewportWidth: 390,
    columnWidth: 327,
    gap: 10,
    columnCount: 3,
  })).toBe(674);
});

test('drop appends the card without counting its old position', () => {
  const cards = [
    card('dragged', 'todo', 9000),
    card('target-a', 'done', 1000),
    card('target-b', 'done', 2000),
  ];
  expect(getAppendPosition(cards, 'done', 'dragged')).toBe(3000);
  expect(moveCardPreview(cards, 'dragged', 'done')[0]).toMatchObject({
    columnId: 'done',
    position: 3000,
  });
});
