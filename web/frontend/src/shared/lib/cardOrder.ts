export const priorityRank: Record<string, number> = {
  low: 1,
  medium: 2,
  high: 3,
  urgent: 4,
};
export function orderCards<
  T extends { priority: string | null; position: number; id: string },
>(cards: readonly T[], byPriority: boolean): T[] {
  return [...cards].sort(
    (a, b) =>
      (byPriority
        ? (priorityRank[b.priority || ''] || 0) -
          (priorityRank[a.priority || ''] || 0)
        : 0) ||
      a.position - b.position ||
      a.id.localeCompare(b.id),
  );
}
