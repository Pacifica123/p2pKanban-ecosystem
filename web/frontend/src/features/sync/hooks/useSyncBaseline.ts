import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getSyncStatus, pullChanges, registerReplica, type Replica, type SyncStatusResponse } from '@/features/sync/api/sync';
import {
  getOrCreateClientReplicaKey,
  loadRegisteredReplica,
  loadSyncCursors,
  saveCursorFromPull,
  saveRegisteredReplica,
  workspaceScopeKey,
} from '@/features/sync/lib/syncReplicaStore';

export type SyncBaselineState = 'idle' | 'registering' | 'ready' | 'pulling' | 'offline' | 'error';

export interface SyncBaselineRuntime {
  state: SyncBaselineState;
  replica: Replica | null;
  status: SyncStatusResponse | null;
  lastError: string | null;
  lastPulledAt: string | null;
  pullWorkspace: () => Promise<void>;
  refreshStatus: () => Promise<void>;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Sync baseline operation failed';
}

export function useSyncBaseline(workspaceId?: string | null): SyncBaselineRuntime {
  const [replica, setReplica] = useState<Replica | null>(() => loadRegisteredReplica());
  const [status, setStatus] = useState<SyncStatusResponse | null>(null);
  const [state, setState] = useState<SyncBaselineState>('idle');
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastPulledAt, setLastPulledAt] = useState<string | null>(null);
  const autoPulledScopeRef = useRef<string | null>(null);

  const isOnline = typeof navigator === 'undefined' ? true : navigator.onLine;

  const refreshStatus = useCallback(async () => {
    if (!replica?.id) return;
    const next = await getSyncStatus(replica.id);
    setStatus(next);
  }, [replica?.id]);

  const pullWorkspace = useCallback(async () => {
    if (!replica?.id || !workspaceId) return;
    const scopeKey = workspaceScopeKey(workspaceId);
    const cursors = loadSyncCursors();
    setState('pulling');
    setLastError(null);
    try {
      const response = await pullChanges({
        replicaId: replica.id,
        scope: 'workspace',
        workspaceId,
        lastServerOrder: cursors[scopeKey] || 0,
        limit: 100,
      });
      saveCursorFromPull(response);
      setLastPulledAt(new Date().toISOString());
      setState('ready');
    } catch (error) {
      setLastError(errorMessage(error));
      setState('error');
    }
  }, [replica?.id, workspaceId]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      if (!isOnline) {
        setState('offline');
        return;
      }

      setState('registering');
      setLastError(null);
      try {
        const response = await registerReplica({
          replicaKey: getOrCreateClientReplicaKey(),
          kind: 'browser_profile',
          displayName: 'Browser profile',
          platform: typeof navigator === 'undefined' ? 'unknown' : navigator.userAgent.slice(0, 160),
          protocolVersion: 'sync-baseline-v1',
        });
        if (cancelled) return;
        saveRegisteredReplica(response.replica);
        setReplica(response.replica);
        const nextStatus = await getSyncStatus(response.replica.id);
        if (cancelled) return;
        setStatus(nextStatus);
        setState('ready');
      } catch (error) {
        if (cancelled) return;
        setLastError(errorMessage(error));
        setState('error');
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [isOnline]);

  useEffect(() => {
    if (state !== 'ready' || !workspaceId || !replica?.id) return;
    const scopeKey = `${replica.id}:${workspaceId}`;
    if (autoPulledScopeRef.current === scopeKey) return;
    autoPulledScopeRef.current = scopeKey;
    void pullWorkspace();
  }, [pullWorkspace, replica?.id, state, workspaceId]);

  return useMemo(() => ({
    state,
    replica,
    status,
    lastError,
    lastPulledAt,
    pullWorkspace,
    refreshStatus,
  }), [lastError, lastPulledAt, pullWorkspace, refreshStatus, replica, state, status]);
}
