import { apiRequest } from '@/shared/api/client';
import type {
  CreatedWorkspaceInvitationResponse,
  Workspace,
  WorkspaceInvitationPreview,
  WorkspaceInvitationsListResponse,
  WorkspaceListResponse,
  WorkspaceMember,
  WorkspaceMembersListResponse,
} from '@/shared/types/api';

export function getWorkspaces() {
  return apiRequest<WorkspaceListResponse>('/workspaces');
}

export function getWorkspace(workspaceId: string) {
  return apiRequest<Workspace & { members: WorkspaceMember[] }>(`/workspaces/${workspaceId}`);
}

export function createWorkspace(input: { name: string; visibility: 'private' | 'shared'; description?: string }) {
  return apiRequest<Workspace>('/workspaces', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateWorkspace(workspaceId: string, input: Partial<Pick<Workspace, 'name' | 'description' | 'visibility'>>) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function archiveWorkspace(workspaceId: string) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}/archive`, {
    method: 'POST',
  });
}

export function getWorkspaceMembers(workspaceId: string) {
  return apiRequest<WorkspaceMembersListResponse>(`/workspaces/${workspaceId}/members`);
}

export function updateWorkspaceMember(
  workspaceId: string,
  memberId: string,
  role: 'member' | 'guest',
) {
  return apiRequest<WorkspaceMember>(`/workspaces/${workspaceId}/members/${memberId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}

export function removeWorkspaceMember(workspaceId: string, memberId: string) {
  return apiRequest<WorkspaceMember>(`/workspaces/${workspaceId}/members/${memberId}`, {
    method: 'DELETE',
  });
}

export function getWorkspaceInvitations(workspaceId: string) {
  return apiRequest<WorkspaceInvitationsListResponse>(`/workspaces/${workspaceId}/invitations`);
}

export function createWorkspaceInvitation(
  workspaceId: string,
  input: { role: 'member' | 'guest'; expiresInHours: number },
) {
  return apiRequest<CreatedWorkspaceInvitationResponse>(`/workspaces/${workspaceId}/invitations`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function revokeWorkspaceInvitation(workspaceId: string, invitationId: string) {
  return apiRequest<WorkspaceInvitationsListResponse['items'][number]>(
    `/workspaces/${workspaceId}/invitations/${invitationId}`,
    { method: 'DELETE' },
  );
}

export function previewWorkspaceInvitation(token: string) {
  return apiRequest<WorkspaceInvitationPreview>(`/invitations/${encodeURIComponent(token)}`);
}

export function acceptWorkspaceInvitation(token: string) {
  return apiRequest<Workspace>(`/invitations/${encodeURIComponent(token)}/accept`, {
    method: 'POST',
  });
}
