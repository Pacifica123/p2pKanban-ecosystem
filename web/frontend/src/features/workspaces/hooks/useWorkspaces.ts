import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  archiveWorkspace,
  createWorkspace,
  createWorkspaceInvitation,
  getWorkspace,
  getWorkspaceInvitations,
  getWorkspaceMembers,
  getWorkspaces,
  removeWorkspaceMember,
  revokeWorkspaceInvitation,
  updateWorkspace,
  updateWorkspaceMember,
} from '@/features/workspaces/api/workspaces';

export const workspacesQueryKey = ['workspaces'];

export function useWorkspacesQuery() {
  return useQuery({
    queryKey: workspacesQueryKey,
    queryFn: getWorkspaces,
    refetchInterval: 8_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateWorkspaceMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createWorkspace,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workspacesQueryKey });
    },
  });
}

export function useUpdateWorkspaceMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workspaceId, input }: { workspaceId: string; input: { name?: string; description?: string; visibility?: 'private' | 'shared' } }) =>
      updateWorkspace(workspaceId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workspacesQueryKey });
    },
  });
}

export function useArchiveWorkspaceMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: archiveWorkspace,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workspacesQueryKey });
    },
  });
}

export function useWorkspaceQuery(workspaceId?: string) {
  return useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => getWorkspace(workspaceId!),
    enabled: Boolean(workspaceId),
  });
}

export function useWorkspaceAccessQueries(workspaceId?: string, isOwner = false) {
  const members = useQuery({
    queryKey: ['workspace-members', workspaceId],
    queryFn: () => getWorkspaceMembers(workspaceId!),
    enabled: Boolean(workspaceId),
  });
  const invitations = useQuery({
    queryKey: ['workspace-invitations', workspaceId],
    queryFn: () => getWorkspaceInvitations(workspaceId!),
    enabled: Boolean(workspaceId && isOwner),
  });
  return { members, invitations };
}

export function useWorkspaceAccessMutations(workspaceId: string) {
  const queryClient = useQueryClient();
  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] }),
    queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] }),
    queryClient.invalidateQueries({ queryKey: ['workspace-invitations', workspaceId] }),
    queryClient.invalidateQueries({ queryKey: workspacesQueryKey }),
  ]);
  return {
    createInvitation: useMutation({
      mutationFn: (input: { role: 'member' | 'guest'; expiresInHours: number }) =>
        createWorkspaceInvitation(workspaceId, input),
      onSuccess: invalidate,
    }),
    revokeInvitation: useMutation({
      mutationFn: (invitationId: string) => revokeWorkspaceInvitation(workspaceId, invitationId),
      onSuccess: invalidate,
    }),
    updateMember: useMutation({
      mutationFn: ({ memberId, role }: { memberId: string; role: 'member' | 'guest' }) =>
        updateWorkspaceMember(workspaceId, memberId, role),
      onSuccess: invalidate,
    }),
    removeMember: useMutation({
      mutationFn: (memberId: string) => removeWorkspaceMember(workspaceId, memberId),
      onSuccess: invalidate,
    }),
  };
}
