import { apiRequest } from '../../../shared/api/client';
import type { BoardSummary, VaultStatus, WorkspaceSummary } from '../../../shared/api/types';

const jsonHeaders = { 'content-type': 'application/json' } as const;

export function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiRequest<WorkspaceSummary[]>('/planner/workspaces');
}

export function createWorkspace(title: string): Promise<WorkspaceSummary> {
  return apiRequest<WorkspaceSummary>('/planner/workspaces', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ title }),
  });
}

export function listBoards(workspaceId: string): Promise<BoardSummary[]> {
  return apiRequest<BoardSummary[]>('/planner/boards/list', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ workspaceId }),
  });
}

export function createBoard(workspaceId: string, title: string): Promise<BoardSummary> {
  return apiRequest<BoardSummary>('/planner/boards', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ workspaceId, title }),
  });
}

export function openBoard(workspaceId: string, boardId: string): Promise<BoardSummary> {
  return apiRequest<BoardSummary>('/planner/boards/open', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ workspaceId, boardId }),
  });
}

export function getVaultStatus(): Promise<VaultStatus> {
  return apiRequest<VaultStatus>('/system/vault-status');
}
