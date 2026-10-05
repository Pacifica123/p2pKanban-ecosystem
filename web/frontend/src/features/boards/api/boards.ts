import { apiRequest } from '@/shared/api/client';
import type { Board, BoardListResponse } from '@/shared/types/api';

export function getBoards(workspaceId: string) {
  return apiRequest<BoardListResponse>(`/workspaces/${workspaceId}/boards`);
}

export function getBoard(boardId: string) {
  return apiRequest<Board>(`/boards/${boardId}`);
}

export function createBoard(workspaceId: string, input: { name: string; description?: string }) {
  return apiRequest<Board>(`/workspaces/${workspaceId}/boards`, {
    method: 'POST',
    body: JSON.stringify({
      ...input,
      boardType: 'kanban',
    }),
  });
}

export function deleteBoard(boardId: string) {
  return apiRequest<Board>(`/boards/${boardId}`, {
    method: 'DELETE',
  });
}

export function updateBoard(boardId: string, input: Partial<Pick<Board, 'name' | 'description'>>) {
  return apiRequest<Board>(`/boards/${boardId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function archiveBoard(boardId: string) {
  return apiRequest<Board>(`/boards/${boardId}/archive`, {
    method: 'POST',
  });
}
