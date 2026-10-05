import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSyncBaseline } from '@/features/sync/hooks/useSyncBaseline';

const api = vi.hoisted(() => ({
  getSyncStatus: vi.fn(),
  pullChanges: vi.fn(),
  registerReplica: vi.fn(),
}));

vi.mock('@/features/sync/api/sync', () => api);

vi.mock('@/features/sync/lib/syncReplicaStore', () => ({
  getOrCreateClientReplicaKey: () => 'replica-key',
  loadRegisteredReplica: () => null,
  loadSyncCursors: () => ({}),
  saveCursorFromPull: vi.fn(),
  saveRegisteredReplica: vi.fn(),
  workspaceScopeKey: (workspaceId: string) => `workspace:${workspaceId}`,
}));

describe('useSyncBaseline automatic pull', () => {
  beforeEach(() => {
    api.getSyncStatus.mockReset();
    api.pullChanges.mockReset();
    api.registerReplica.mockReset();

    api.registerReplica.mockResolvedValue({
      replica: {
        id: 'replica-1',
        replicaKey: 'replica-key',
        kind: 'browser_profile',
      },
    });
    api.getSyncStatus.mockResolvedValue({
      maxServerOrder: 0,
    });
    api.pullChanges.mockResolvedValue({
      events: [],
      nextCursor: null,
      hasMore: false,
    });
  });

  it('pulls once per replica and workspace instead of looping after ready', async () => {
    const { rerender } = renderHook(
      ({ workspaceId }) => useSyncBaseline(workspaceId),
      { initialProps: { workspaceId: 'workspace-1' } },
    );

    await waitFor(() => expect(api.pullChanges).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.getSyncStatus).toHaveBeenCalledTimes(1));

    rerender({ workspaceId: 'workspace-1' });
    await new Promise((resolve) => window.setTimeout(resolve, 20));
    expect(api.pullChanges).toHaveBeenCalledTimes(1);

    rerender({ workspaceId: 'workspace-2' });
    await waitFor(() => expect(api.pullChanges).toHaveBeenCalledTimes(2));
  });
});
