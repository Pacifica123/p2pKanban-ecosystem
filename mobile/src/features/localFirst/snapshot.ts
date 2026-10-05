import {
  getBoard,
  getBoardAppearance,
  getCards,
  getChecklists,
  getColumns,
} from '../../shared/api/endpoints';
import type { Card, Checklist } from '../../shared/types/api';
import {
  LOCAL_SCHEMA_VERSION,
  type LocalBoardSnapshot,
} from './model';

async function mapWithConcurrency<T, R>(
  values: T[],
  concurrency: number,
  mapper: (value: T) => Promise<R>,
) {
  const results = new Array<R>(values.length);
  let nextIndex = 0;
  async function worker() {
    while (nextIndex < values.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await mapper(values[index]!);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(concurrency, values.length) }, () => worker()),
  );
  return results;
}

async function fetchChecklistEntry(card: Card) {
  const response = await getChecklists(card.id);
  return [card.id, response.items] as const;
}

export async function fetchBoardSnapshot(
  boardId: string,
  workspaceId: string,
): Promise<LocalBoardSnapshot> {
  const [board, appearance, columns, cards] = await Promise.all([
    getBoard(boardId),
    getBoardAppearance(boardId),
    getColumns(boardId),
    getCards(boardId),
  ]);
  const checklistEntries = await mapWithConcurrency(
    cards.items,
    4,
    fetchChecklistEntry,
  );
  const checklistsByCardId = Object.fromEntries(checklistEntries) as Record<string, Checklist[]>;
  const timestamp = new Date().toISOString();
  return {
    schemaVersion: LOCAL_SCHEMA_VERSION,
    workspaceId,
    board,
    appearance,
    columns: columns.items.sort((left, right) => left.position - right.position),
    cards: cards.items,
    checklistsByCardId,
    checklistsHydratedAt: timestamp,
    cachedAt: timestamp,
    lastServerRefreshAt: timestamp,
  };
}
