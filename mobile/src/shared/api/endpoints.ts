import type {
  ActivityListResponse,
  Board,
  BoardColumn,
  BoardLabel,
  BoardLabelListResponse,
  BoardListResponse,
  BoardAppearanceSettings,
  BackendVersionResponse,
  Card,
  CardListResponse,
  Checklist,
  ChecklistItem,
  ChecklistListResponse,
  Comment,
  CommentListResponse,
  ColumnListResponse,
  NativeAuthSuccessResponse,
  Replica,
  RoamingCapabilityResponse,
  SessionResponse,
  SyncStatusResponse,
  UpdateBoardAppearanceRequest,
  UpdateUserAppearancePreferencesRequest,
  UserAppearancePreferences,
  Workspace,
  WorkspaceInvitation,
  CreatedWorkspaceInvitationResponse,
  WorkspaceInvitationsListResponse,
  WorkspaceListResponse,
  WorkspaceMember,
  WorkspaceMembersListResponse,
} from '../types/api';
import { apiRequest } from './client';

export function getBackendVersion() {
  return apiRequest<BackendVersionResponse>('/health', {}, { skipRefresh: true });
}

function normalizeUserAppearance(value: UserAppearancePreferences): UserAppearancePreferences {
  return {
    ...value,
    checklistItemSubmitMode: value.checklistItemSubmitMode || 'ctrl_enter',
    cardDetailsMode: value.cardDetailsMode || 'drawer',
  };
}

export async function getMyAppearance() {
  return normalizeUserAppearance(
    await apiRequest<UserAppearancePreferences>('/me/appearance'),
  );
}

export async function updateMyAppearance(input: UpdateUserAppearancePreferencesRequest) {
  return normalizeUserAppearance(
    await apiRequest<UserAppearancePreferences>('/me/appearance', {
      method: 'PUT',
      body: JSON.stringify(input),
    }),
  );
}

export function getBoardAppearance(boardId: string) {
  return apiRequest<BoardAppearanceSettings>(`/boards/${boardId}/appearance`);
}

export function updateBoardAppearance(boardId: string, input: UpdateBoardAppearanceRequest) {
  return apiRequest<BoardAppearanceSettings>(`/boards/${boardId}/appearance`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}

export function nativeSignIn(input: { email: string; password: string }) {
  return apiRequest<NativeAuthSuccessResponse>(
    '/auth/native/sign-in',
    { method: 'POST', body: JSON.stringify(input) },
    { skipRefresh: true },
  );
}

export function nativeSignUp(input: { email: string; password: string; displayName: string }) {
  return apiRequest<NativeAuthSuccessResponse>(
    '/auth/native/sign-up',
    { method: 'POST', body: JSON.stringify(input) },
    { skipRefresh: true },
  );
}

export function nativeRefresh(refreshToken: string) {
  return apiRequest<NativeAuthSuccessResponse>(
    '/auth/native/refresh',
    { method: 'POST', body: JSON.stringify({ refreshToken }) },
    { skipRefresh: true },
  );
}

export function nativeSignOut(refreshToken: string) {
  return apiRequest<{ signedOut: boolean; mode: string }>(
    '/auth/native/sign-out',
    { method: 'POST', body: JSON.stringify({ refreshToken }) },
    { skipRefresh: true },
  );
}

export function signOutAll() {
  return apiRequest<{ signedOut: boolean; mode: string }>('/auth/sign-out-all', {
    method: 'POST',
  });
}

export function getSession() {
  return apiRequest<SessionResponse>('/auth/session');
}

export function getWorkspaces() {
  return apiRequest<WorkspaceListResponse>('/workspaces');
}

export function getWorkspace(workspaceId: string) {
  return apiRequest<Workspace & { members: WorkspaceMember[] }>(`/workspaces/${workspaceId}`);
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
  return apiRequest<WorkspaceInvitation>(
    `/workspaces/${workspaceId}/invitations/${invitationId}`,
    { method: 'DELETE' },
  );
}

export function createWorkspace(input: {
  name: string;
  visibility: 'private' | 'shared';
  description?: string;
}) {
  return apiRequest<Workspace>('/workspaces', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateWorkspace(
  workspaceId: string,
  input: Partial<Pick<Workspace, 'name' | 'description' | 'visibility'>>,
) {
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

export function deleteWorkspace(workspaceId: string) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}`, {
    method: 'DELETE',
  });
}

export function getBoards(workspaceId: string) {
  return apiRequest<BoardListResponse>(`/workspaces/${workspaceId}/boards`);
}

export function createBoard(workspaceId: string, input: { name: string; description?: string }) {
  return apiRequest<Board>(`/workspaces/${workspaceId}/boards`, {
    method: 'POST',
    body: JSON.stringify({ ...input, boardType: 'kanban' }),
  });
}

export function updateBoard(
  boardId: string,
  input: Partial<Pick<Board, 'name' | 'description'>>,
) {
  return apiRequest<Board>(`/boards/${boardId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function archiveBoard(boardId: string) {
  return apiRequest<Board>(`/boards/${boardId}/archive`, { method: 'POST' });
}

export function deleteBoard(boardId: string) {
  return apiRequest<Board>(`/boards/${boardId}`, { method: 'DELETE' });
}

export function getBoard(boardId: string) {
  return apiRequest<Board>(`/boards/${boardId}`);
}

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

export function updateColumn(
  boardId: string,
  columnId: string,
  input: Partial<Pick<
    BoardColumn,
    'name' | 'description' | 'position' | 'colorToken' | 'wipLimit'
  >>,
) {
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

export function getCards(boardId: string) {
  return apiRequest<CardListResponse>(`/boards/${boardId}/cards`);
}

export function getChecklists(cardId: string) {
  return apiRequest<ChecklistListResponse>(`/cards/${cardId}/checklists`);
}

export function createChecklist(
  cardId: string,
  input: { title: string; position?: number | null },
) {
  return apiRequest<Checklist>(`/cards/${cardId}/checklists`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateChecklist(
  checklistId: string,
  input: { title?: string; position?: number | null },
) {
  return apiRequest<Checklist>(`/checklists/${checklistId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteChecklist(checklistId: string) {
  return apiRequest<Checklist>(`/checklists/${checklistId}`, { method: 'DELETE' });
}

export function createChecklistItem(
  checklistId: string,
  input: { title: string; position?: number | null },
) {
  return apiRequest<ChecklistItem>(`/checklists/${checklistId}/items`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateChecklistItem(
  itemId: string,
  input: { title?: string; position?: number | null; isDone?: boolean | null },
) {
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

export function createCard(boardId: string, input: {
  title: string;
  description?: string;
  columnId: string;
  priority?: Card['priority'];
}) {
  return apiRequest<Card>(`/boards/${boardId}/cards`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateCard(cardId: string, input: Partial<Pick<
  Card,
  'title' | 'description' | 'priority' | 'startAt' | 'dueAt'
>>) {
  return apiRequest<Card>(`/cards/${cardId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function moveCard(cardId: string, input: { targetColumnId: string; position?: number | null }) {
  return apiRequest<Card>(`/cards/${cardId}/move`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function archiveCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}/archive`, { method: 'POST' });
}

export function unarchiveCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}/unarchive`, { method: 'POST' });
}

export function deleteCard(cardId: string) {
  return apiRequest<Card>(`/cards/${cardId}?scope=all_devices`, { method: 'DELETE' });
}

export function getBoardLabels(boardId: string) {
  return apiRequest<BoardLabelListResponse>(`/boards/${boardId}/labels`);
}

export function createBoardLabel(
  boardId: string,
  input: { name: string; color: string; description?: string | null },
) {
  return apiRequest<BoardLabel>(`/boards/${boardId}/labels`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateBoardLabel(
  labelId: string,
  input: { name?: string; color?: string; description?: string | null },
) {
  return apiRequest<BoardLabel>(`/labels/${labelId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export function deleteBoardLabel(labelId: string) {
  return apiRequest<BoardLabel>(`/labels/${labelId}`, { method: 'DELETE' });
}

export function replaceCardLabels(cardId: string, labelIds: string[]) {
  return apiRequest<Card>(`/cards/${cardId}/labels`, {
    method: 'PUT',
    body: JSON.stringify({ labelIds }),
  });
}

export function getCardComments(cardId: string) {
  return apiRequest<CommentListResponse>(`/cards/${cardId}/comments`);
}

export function createComment(cardId: string, body: string) {
  return apiRequest<Comment>(`/cards/${cardId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });
}

export function updateComment(commentId: string, body: string) {
  return apiRequest<Comment>(`/comments/${commentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ body }),
  });
}

export function deleteComment(commentId: string) {
  return apiRequest<Comment>(`/comments/${commentId}`, { method: 'DELETE' });
}

export function getBoardActivity(boardId: string) {
  return apiRequest<ActivityListResponse>(`/boards/${boardId}/activity?limit=60`);
}

export function registerReplica(input: {
  replicaKey: string;
  displayName: string;
  platform: string;
  appVersion: string;
}) {
  return apiRequest<{ replica: Replica }>('/sync/replicas', {
    method: 'POST',
    body: JSON.stringify({
      ...input,
      kind: 'device',
      protocolVersion: 'sync-baseline-v1',
      metadata: { shell: 'react-native-expo' },
    }),
  });
}

export function getSyncStatus(replicaId: string) {
  return apiRequest<SyncStatusResponse>(`/sync/status?replicaId=${encodeURIComponent(replicaId)}`);
}

export function pullWorkspace(input: {
  replicaId: string;
  workspaceId: string;
  lastServerOrder: number;
}) {
  const query = new URLSearchParams({
    replicaId: input.replicaId,
    scope: 'workspace',
    workspaceId: input.workspaceId,
    lastServerOrder: String(input.lastServerOrder),
    limit: '100',
  });
  return apiRequest<{
    events: unknown[];
    nextCursor: {
      scope: { scope: 'workspace'; workspaceId: string };
      replicaId: string;
      lastServerOrder: number;
    };
    hasMore: boolean;
  }>(`/sync/pull?${query.toString()}`);
}

export function provisionRoamingBoard(boardId: string, authorPublicKey: string) {
  return apiRequest<RoamingCapabilityResponse>(
    '/sync/roaming/capability',
    {
      method: 'POST',
      body: JSON.stringify({ boardId, authorPublicKey }),
    },
  );
}
