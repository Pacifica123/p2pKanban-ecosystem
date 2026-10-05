import type { Workspace, WorkspaceListResponse } from '@/shared/types/api';

export function makeWorkspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    id: overrides.id || 'workspace-1',
    name: overrides.name || 'Personal',
    slug: overrides.slug ?? null,
    description: overrides.description ?? 'Default workspace for frontend tests.',
    visibility: overrides.visibility || 'private',
    ownerUserId: overrides.ownerUserId || 'user-1',
    memberCount: overrides.memberCount ?? 1,
    isArchived: overrides.isArchived ?? false,
    createdAt: overrides.createdAt || '2026-04-14T10:00:00Z',
    updatedAt: overrides.updatedAt || '2026-04-14T10:05:00Z',
    archivedAt: overrides.archivedAt ?? null,
  };
}

export function makeWorkspaceListResponse(items: Workspace[] = []): WorkspaceListResponse {
  return {
    items,
    pageInfo: {
      nextCursor: null,
      prevCursor: null,
      hasNextPage: false,
      hasPrevPage: false,
    },
  };
}
