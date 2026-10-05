import type { Card } from '@/shared/types/api';

export interface ChecklistProgress {
  completed: number;
  total: number;
  percent: number;
}

export function getChecklistProgress(card: Card): ChecklistProgress | null {
  const total = Math.max(0, card.checklistItemCount || 0);
  if (!total) return null;
  const completed = Math.min(
    total,
    Math.max(0, card.checklistCompletedItemCount || 0),
  );
  return {
    completed,
    total,
    percent: Math.round((completed / total) * 100),
  };
}
