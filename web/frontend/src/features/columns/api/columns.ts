import { apiRequest } from '@/shared/api/client';
import type { BoardColumn, ColumnListResponse } from '@/shared/types/api';

export function getColumns(boardId: string) {
  return apiRequest<ColumnListResponse>(`/boards/${boardId}/columns`);
}

export function createColumn(boardId: string, input: {
  name: string;
  description?: string;
  position?: number;
  colorToken?: string;
  wipLimit?: number;
}) {
  return apiRequest<BoardColumn>(`/boards/${boardId}/columns`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateColumn(boardId: string, columnId: string, input: Partial<Pick<BoardColumn, 'name' | 'description' | 'position' | 'colorToken' | 'wipLimit'>>) {
  return apiRequest<BoardColumn>(`/boards/${boardId}/columns/${columnId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteColumn(boardId: string, columnId: string) {
  return apiRequest<BoardColumn>(`/boards/${boardId}/columns/${columnId}`, {
    method: 'DELETE',
  });
}
