import { describe, expect, it } from 'vitest';
import type { Card } from '@/shared/types/api';
import { getChecklistProgress } from '@/features/boards/lib/checklistProgress';

function card(input: Partial<Card> = {}): Card {
  return {
    id: 'card-1',
    boardId: 'board-1',
    columnId: 'column-1',
    title: 'Карточка',
    priority: null,
    position: 1000,
    isArchived: false,
    createdAt: '2026-07-29T00:00:00.000Z',
    updatedAt: '2026-07-29T00:00:00.000Z',
    ...input,
  };
}

describe('getChecklistProgress', () => {
  it('hides progress when all checklists are empty', () => {
    expect(getChecklistProgress(card({
      checklistCount: 2,
      checklistItemCount: 0,
      checklistCompletedItemCount: 0,
    }))).toBeNull();
  });

  it('uses total checklist items instead of checklist count', () => {
    expect(getChecklistProgress(card({
      checklistCount: 2,
      checklistItemCount: 5,
      checklistCompletedItemCount: 3,
    }))).toEqual({ completed: 3, total: 5, percent: 60 });
  });
});
