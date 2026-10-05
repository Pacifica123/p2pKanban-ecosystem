import { apiRequest } from '@/shared/api/client';
import type { Checklist, ChecklistItem, ChecklistListResponse } from '@/shared/types/api';

export function getCardChecklists(cardId: string) {
  return apiRequest<ChecklistListResponse>(`/cards/${cardId}/checklists`);
}

export function createChecklist(cardId: string, input: { title: string; position?: number | null }) {
  return apiRequest<Checklist>(`/cards/${cardId}/checklists`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateChecklist(checklistId: string, input: { title?: string; position?: number | null }) {
  return apiRequest<Checklist>(`/checklists/${checklistId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteChecklist(checklistId: string) {
  return apiRequest<Checklist>(`/checklists/${checklistId}`, {
    method: 'DELETE',
  });
}

export function createChecklistItem(checklistId: string, input: { title: string; position?: number | null }) {
  return apiRequest<ChecklistItem>(`/checklists/${checklistId}/items`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateChecklistItem(itemId: string, input: { title?: string; position?: number | null; isDone?: boolean | null }) {
  return apiRequest<ChecklistItem>(`/checklist-items/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteChecklistItem(itemId: string) {
  return apiRequest<ChecklistItem>(`/checklist-items/${itemId}`, {
    method: 'DELETE',
  });
}
