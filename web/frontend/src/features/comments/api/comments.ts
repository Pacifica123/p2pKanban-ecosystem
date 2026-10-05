import { apiRequest } from '@/shared/api/client';
import type { Comment, CommentListResponse } from '@/shared/types/api';

export function getCardComments(cardId: string) {
  return apiRequest<CommentListResponse>(`/cards/${cardId}/comments`);
}

export function createComment(cardId: string, input: { body: string }) {
  return apiRequest<Comment>(`/cards/${cardId}/comments`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateComment(commentId: string, input: { body: string }) {
  return apiRequest<Comment>(`/comments/${commentId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteComment(commentId: string) {
  return apiRequest<Comment>(`/comments/${commentId}`, {
    method: 'DELETE',
  });
}
