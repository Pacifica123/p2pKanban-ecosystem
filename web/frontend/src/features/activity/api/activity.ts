import { apiRequest } from '@/shared/api/client';
import type {
  ActivityListResponse,
  BoardProductivityResponse,
} from '@/shared/types/api';

export function getBoardActivity(boardId: string) {
  return apiRequest<ActivityListResponse>(`/boards/${boardId}/activity`);
}

export function getCardActivity(cardId: string) {
  return apiRequest<ActivityListResponse>(`/cards/${cardId}/activity`);
}

export function getBoardProductivity(boardId: string) {
  return apiRequest<BoardProductivityResponse>(
    `/boards/${boardId}/productivity`,
  );
}
