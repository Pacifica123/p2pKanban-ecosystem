// «Очистить колонку»: every card of one column deleted on all devices, one by one
// through the same DELETE /cards/{id}?scope=all_devices as the card window, so
// each deletion travels to the other nodes and phones as an ordinary card.delete.
import { ApiError } from '@/shared/api/errors';
import type { Card } from '@/shared/types/api';

export interface ClearColumnResult {
  deleted: number;
  /** Already gone on the node (another device, or removed with its parent). */
  missing: number;
  /** The first failure stops the run; the cards after it are left alone. */
  error: unknown;
}

/** Cards of `columnId`, subtasks before their parents. */
export function cardsToClear(cards: Card[], columnId: string) {
  const own = cards.filter((card) => card.columnId === columnId);
  return [...own.filter((card) => card.parentCardId), ...own.filter((card) => !card.parentCardId)];
}

export async function clearColumnCards(
  cards: Card[],
  remove: (cardId: string) => Promise<unknown>,
  onProgress?: (done: number, total: number) => void,
): Promise<ClearColumnResult> {
  const result: ClearColumnResult = { deleted: 0, missing: 0, error: null };
  for (const card of cards) {
    try {
      await remove(card.id);
      result.deleted += 1;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        result.missing += 1;
      } else {
        result.error = error;
        break;
      }
    }
    onProgress?.(result.deleted + result.missing, cards.length);
  }
  return result;
}
