import { apiRequest } from '../../../shared/api/client';
import type {
  ActivitySummary,
  AppearanceSummary,
  CommentSummary,
  LabelSummary,
  ParityUnsyncedCount,
} from '../../../shared/api/types';

const jsonHeaders = { 'content-type': 'application/json' } as const;

function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return apiRequest<T>(path, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });
}

export function listLabels(workspaceId: string, boardId: string): Promise<LabelSummary[]> {
  return post('/parity/labels/list', { workspaceId, boardId });
}

export function createLabel(workspaceId: string, boardId: string, name: string, color: string): Promise<LabelSummary> {
  return post('/parity/labels', { workspaceId, boardId, name, color: color || null });
}

export function deleteLabel(workspaceId: string, boardId: string, labelId: string): Promise<void> {
  return post('/parity/labels/delete', { workspaceId, boardId, labelId });
}

export function listCardLabelIds(workspaceId: string, cardId: string): Promise<string[]> {
  return post('/parity/card-labels/list', { workspaceId, cardId });
}

export function setCardLabel(workspaceId: string, cardId: string, labelId: string, assigned: boolean): Promise<void> {
  return post('/parity/card-labels/set', { workspaceId, cardId, labelId, assigned });
}

export function listComments(workspaceId: string, cardId: string): Promise<CommentSummary[]> {
  return post('/parity/comments/list', { workspaceId, cardId });
}

export function createComment(workspaceId: string, cardId: string, body: string): Promise<CommentSummary> {
  return post('/parity/comments', { workspaceId, cardId, body });
}

export function deleteComment(workspaceId: string, commentId: string): Promise<void> {
  return post('/parity/comments/delete', { workspaceId, commentId });
}

export function getAppearance(workspaceId: string, boardId: string): Promise<AppearanceSummary> {
  return post('/parity/appearance/get', { workspaceId, boardId });
}

export function setAppearance(workspaceId: string, boardId: string, settingsJson: string): Promise<AppearanceSummary> {
  return post('/parity/appearance/set', { workspaceId, boardId, settingsJson });
}

export function listActivity(workspaceId: string, boardId: string, limit = 50): Promise<ActivitySummary[]> {
  return post('/parity/activity/list', { workspaceId, boardId, limit });
}

export function getUnsyncedParityCount(workspaceId: string, boardId: string): Promise<ParityUnsyncedCount> {
  return post('/parity/unsynced-count', { workspaceId, boardId });
}
