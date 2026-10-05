import { describe, expect, it } from 'vitest';
import { groupCardsByColumn, reorderBoardPreview } from '@/features/boards/lib/cardDnd';
import type { Card } from '@/shared/types/api';

function card(id: string, columnId: string, position: number): Card {
  return {
    id,
    boardId: 'board-1',
    columnId,
    parentCardId: null,
    title: id,
    description: null,
    priority: null,
    position,
    startAt: null,
    dueAt: null,
    isArchived: false,
    labelIds: [],
    checklistCount: 0,
    checklistCompletedItemCount: 0,
    commentCount: 0,
    createdByUserId: null,
    createdAt: `2026-07-26T00:00:0${position}.000Z`,
    updatedAt: `2026-07-26T00:00:0${position}.000Z`,
    archivedAt: null,
  };
}

describe('card drag-and-drop preview', () => {
  it('keeps all cards and moves the first card after existing cards', () => {
    const cards = [
      card('first', 'column-a', 1),
      card('second', 'column-a', 2),
      card('third', 'column-a', 3),
    ];

    const result = reorderBoardPreview(cards, {
      cardId: 'first',
      sourceColumnId: 'column-a',
      sourceIndex: 0,
      targetColumnId: 'column-a',
      targetIndex: 2,
    });

    expect(groupCardsByColumn(result).get('column-a')?.map((item) => item.id)).toEqual([
      'second',
      'third',
      'first',
    ]);
    expect(result).toHaveLength(cards.length);
  });

  it('moves a card into a populated column without duplicating or dropping it', () => {
    const cards = [
      card('moving', 'column-a', 1),
      card('before', 'column-b', 1),
      card('after', 'column-b', 2),
    ];

    const result = reorderBoardPreview(cards, {
      cardId: 'moving',
      sourceColumnId: 'column-a',
      sourceIndex: 0,
      targetColumnId: 'column-b',
      targetIndex: 1,
    });

    expect(groupCardsByColumn(result).get('column-a') || []).toEqual([]);
    expect(groupCardsByColumn(result).get('column-b')?.map((item) => item.id)).toEqual([
      'before',
      'moving',
      'after',
    ]);
    expect(new Set(result.map((item) => item.id)).size).toBe(cards.length);
  });
});
