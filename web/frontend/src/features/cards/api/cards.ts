import { apiRequest } from '@/shared/api/client';
import type { Card, CardListResponse } from '@/shared/types/api';

export interface MoveCardInput {
  targetColumnId: string;
  position?: number | null;
}

export interface ReorderColumnCardsInput {
  items: Array<{
    cardId: string;
    position: number;
  }>;
}

export type CardLocalVisibility = 'visible' | 'hidden' | 'all';

export function getCards(boardId: string, localVisibility: CardLocalVisibility = 'visible') {
  const query = new URLSearchParams({ localVisibility });
  return apiRequest<CardListResponse>(`/boards/${boardId}/cards` + `?${query.toString()}`);
}

export function getCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}`);
}

export function createCard(boardId: string, input: {
  title: string;
  description?: string;
  columnId: string;
  parentCardId?: string;
  position?: number;
  priority?: Card['priority'];
  startAt?: string;
  dueAt?: string;
}) {
  return apiRequest<Card>(`/boards/${boardId}/cards`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateCard(cardId: string, input: {
  title?: string;
  description?: string | null;
  columnId?: string;
  parentCardId?: string | null;
  priority?: Card['priority'];
  position?: number;
  startAt?: string | null;
  dueAt?: string | null;
  isArchived?: boolean;
}) {
  return apiRequest<Card>(`/cards/${cardId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function moveCard(cardId: string, input: MoveCardInput) {
  return apiRequest<Card>(`/cards/${cardId}/move`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function reorderColumnCards(columnId: string, input: ReorderColumnCardsInput) {
  return apiRequest<CardListResponse>(`/columns/${columnId}/cards/reorder`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function archiveCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}/archive`, {
    method: 'POST',
  });
}

export function unarchiveCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}/unarchive`, {
    method: 'POST',
  });
}

export function deleteCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}` + '?scope=all_devices', {
    method: 'DELETE',
  });
}

export function hideCardLocally(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}/hide-local`, {
    method: 'POST',
  });
}

export function unhideCardLocally(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}/hide-local`, {
    method: 'DELETE',
  });
}
