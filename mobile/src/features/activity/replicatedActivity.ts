import type {ActivityEntry, ActivityListResponse} from '../../shared/types/api';
import {getBoardActivity} from '../../shared/api/endpoints';
import type {LocalOperation} from '../localFirst/model';
import type {RoamingBoardEvent} from '../roaming/types';
import {loadJournal, serializeReplica} from '../roaming/journal';
import {loadRoamingCapability, pullRoamingBoard} from '../roaming/service';

const BOARD_HISTORY_KINDS = new Set(["board.created", "board.updated", "board.archived", "board.deleted", "board.appearance.updated", "column.created", "column.updated", "column.deleted", "column.reordered", "card.created", "card.updated", "card.moved", "card.reordered", "card.archived", "card.restored", "card.deleted", "card.labels.updated", "label.created", "label.updated", "label.deleted", "checklist.created", "checklist.updated", "checklist.deleted", "checklist_item.created", "checklist_item.updated", "checklist_item.completed", "checklist_item.reopened", "checklist_item.deleted", "comment.created", "comment.updated", "comment.deleted"]);

// History is a replicated feed. The journal includes all authenticated authors,
// and is also its offline cache; snapshots and delivery retries are not actions.
export function commonActivity(events: RoamingBoardEvent[], boardId: string): ActivityEntry[] {
  const entries = new Map<string,ActivityEntry>();
  for (const event of events) {
    if (event.boardId !== boardId) continue;
    const entry = event.payload.activity as ActivityEntry | undefined;
    if (!entry || !BOARD_HISTORY_KINDS.has(entry.kind) || entry.boardId !== boardId || typeof entry.id !== 'string'
      || typeof entry.kind !== 'string' || !Number.isFinite(Date.parse(entry.createdAt))
      || !Array.isArray(entry.fieldMask) || !entry.actor) continue;
    entries.set(entry.id,entry);
  }
  return [...entries.values()].sort((a,b) => b.createdAt.localeCompare(a.createdAt) || b.id.localeCompare(a.id));
}

export async function getCommonBoardActivity(boardId: string, online: boolean): Promise<ActivityListResponse & {stale?:boolean}> {
  const capability = await loadRoamingCapability(boardId);
  if (!capability) return getBoardActivity(boardId);
  let stale = !online;
  if (online) {
    try { await pullRoamingBoard(capability,null); }
    catch { stale = true; }
  }
  const items = await serializeReplica(async () => commonActivity((await loadJournal(capability,null)).events,boardId));
  if (stale && !items.length && online) throw new Error('Реле не ответили. Общая история ещё не сохранена на устройстве.');
  return {items,nextCursor:null,stale};
}
