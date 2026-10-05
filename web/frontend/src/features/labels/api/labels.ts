import { apiRequest } from '@/shared/api/client';
import type { BoardLabel, BoardLabelListResponse, Card } from '@/shared/types/api';

export function getBoardLabels(boardId: string) {
  return apiRequest<BoardLabelListResponse>(`/boards/${boardId}/labels`);
}

export function createBoardLabel(boardId: string, input: { name: string; color: string; description?: string | null }) {
  return apiRequest<BoardLabel>(`/boards/${boardId}/labels`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateBoardLabel(labelId: string, input: { name?: string; color?: string; description?: string | null }) {
  return apiRequest<BoardLabel>(`/labels/${labelId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteBoardLabel(labelId: string) {
  return apiRequest<BoardLabel>(`/labels/${labelId}`, {
    method: 'DELETE',
  });
}

export function replaceCardLabels(cardId: string, labelIds: string[]) {
  return apiRequest<Card>(`/cards/${cardId}/labels`, {
    method: 'PUT',
    body: JSON.stringify({ labelIds }),
  });
}
