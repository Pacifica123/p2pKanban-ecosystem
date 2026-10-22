import { expect, test, vi } from 'vitest';
import { cardsToClear, clearColumnCards } from '@/features/cards/lib/clearColumn';
import { ApiError } from '@/shared/api/errors';
import type { Card } from '@/shared/types/api';

const card = (id: string, columnId: string, extra: Partial<Card> = {}) => ({ id, columnId, title: id, ...extra }) as Card;

test('only the chosen column, archived included, subtasks before parents', () => {
  const cards = [
    card('parent', 'done'),
    card('other', 'todo'),
    card('child', 'done', { parentCardId: 'parent' }),
    card('old', 'done', { isArchived: true }),
  ];
  expect(cardsToClear(cards, 'done').map((item) => item.id)).toEqual(['child', 'parent', 'old']);
  expect(cardsToClear(cards, 'empty')).toEqual([]);
});

test('deletes one by one, a card already gone is not an error', async () => {
  const remove = vi.fn(async (id: string) => {
    if (id === 'b') throw new ApiError('Card not found', { status: 404 });
  });
  const progress = vi.fn();
  const result = await clearColumnCards([card('a', 'c'), card('b', 'c'), card('c', 'c')], remove, progress);
  expect(remove.mock.calls.map(([id]) => id)).toEqual(['a', 'b', 'c']);
  expect(result).toEqual({ deleted: 2, missing: 1, error: null });
  expect(progress).toHaveBeenLastCalledWith(3, 3);
});

test('the first real failure stops the run and is reported', async () => {
  const failure = new ApiError('Узел недоступен', { status: 0 });
  const remove = vi.fn(async (id: string) => { if (id === 'b') throw failure; });
  const result = await clearColumnCards([card('a', 'c'), card('b', 'c'), card('c', 'c')], remove);
  expect(remove).toHaveBeenCalledTimes(2);
  expect(result).toEqual({ deleted: 1, missing: 0, error: failure });
});
