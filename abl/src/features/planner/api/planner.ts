import { apiRequest } from '../../../shared/api/client';
import type {
  CardSummary,
  ChecklistItemSummary,
  ChecklistSummary,
  ColumnSummary,
  PendingChangeCount,
} from '../../../shared/api/types';

const jsonHeaders = { 'content-type': 'application/json' } as const;

function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return apiRequest<T>(path, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });
}

export function listColumns(workspaceId: string, boardId: string): Promise<ColumnSummary[]> {
  return post('/planner/columns/list', { workspaceId, boardId });
}

export function createColumn(workspaceId: string, boardId: string, title: string): Promise<ColumnSummary> {
  return post('/planner/columns', { workspaceId, boardId, title });
}

export function listCards(
  workspaceId: string,
  boardId: string,
  includeArchived: boolean,
): Promise<CardSummary[]> {
  return post('/planner/cards/list', { workspaceId, boardId, includeArchived });
}

export function createCard(
  workspaceId: string,
  boardId: string,
  columnId: string,
  title: string,
): Promise<CardSummary> {
  return post('/planner/cards', { workspaceId, boardId, columnId, title });
}

export function moveCard(workspaceId: string, cardId: string, targetColumnId: string): Promise<CardSummary> {
  return post('/planner/cards/move', { workspaceId, cardId, targetColumnId });
}

export function swapCardOrder(workspaceId: string, cardId: string, otherCardId: string): Promise<void> {
  return post('/planner/cards/swap-order', { workspaceId, cardId, otherCardId });
}

export function setCardArchived(workspaceId: string, cardId: string, archived: boolean): Promise<CardSummary> {
  return post('/planner/cards/archive', { workspaceId, cardId, archived });
}

export function deleteCard(workspaceId: string, cardId: string): Promise<void> {
  return post('/planner/cards/delete', { workspaceId, cardId });
}

export function listChecklists(workspaceId: string, cardId: string): Promise<ChecklistSummary[]> {
  return post('/planner/checklists/list', { workspaceId, cardId });
}

export function createChecklist(workspaceId: string, cardId: string, title: string): Promise<ChecklistSummary> {
  return post('/planner/checklists', { workspaceId, cardId, title });
}

export function deleteChecklist(workspaceId: string, checklistId: string): Promise<void> {
  return post('/planner/checklists/delete', { workspaceId, checklistId });
}

export function listChecklistItems(workspaceId: string, checklistId: string): Promise<ChecklistItemSummary[]> {
  return post('/planner/checklist-items/list', { workspaceId, checklistId });
}

export function createChecklistItem(
  workspaceId: string,
  checklistId: string,
  title: string,
): Promise<ChecklistItemSummary> {
  return post('/planner/checklist-items', { workspaceId, checklistId, title });
}

export function setChecklistItemDone(
  workspaceId: string,
  itemId: string,
  done: boolean,
): Promise<ChecklistItemSummary> {
  return post('/planner/checklist-items/done', { workspaceId, itemId, done });
}

export function deleteChecklistItem(workspaceId: string, itemId: string): Promise<void> {
  return post('/planner/checklist-items/delete', { workspaceId, itemId });
}

export function getPendingChangeCount(workspaceId: string, boardId: string): Promise<PendingChangeCount> {
  return post('/planner/pending-count', { workspaceId, boardId });
}
