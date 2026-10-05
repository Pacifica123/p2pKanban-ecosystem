import { apiRequest } from '@/shared/api/client';

export interface Replica {
  id: string;
  replicaKey?: string | null;
  kind: string;
  status: 'active' | 'disabled';
  userId?: string | null;
  deviceId?: string | null;
  displayName?: string | null;
  platform?: string | null;
  protocolVersion?: string | null;
  appVersion?: string | null;
  lastSeenAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RegisterReplicaRequest {
  replicaKey: string;
  kind?: 'browser_profile' | 'device' | 'import_worker' | 'client';
  displayName?: string | null;
  platform?: string | null;
  protocolVersion?: string | null;
  appVersion?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface RegisterReplicaResponse {
  replica: Replica;
}

export interface ReplicaListResponse {
  items: Replica[];
}

export interface SyncStatusResponse {
  healthy: boolean;
  mode: string;
  serverTime: string;
  maxServerOrder?: number | null;
  replica?: Replica | null;
}

export interface ClientChangeEvent {
  eventId: string;
  replicaId: string;
  replicaSeq: number;
  entityType: string;
  entityId: string;
  operation: 'create' | 'update' | 'delete' | 'restore' | 'reorder' | 'add' | 'remove' | 'archive' | 'unarchive';
  fieldMask?: string[];
  logicalClock: number;
  baseServerOrder?: number | null;
  occurredAt?: string | null;
  payload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface PushChangesResponse {
  results: Array<{
    eventId: string;
    replicaSeq: number;
    status: 'accepted' | 'duplicate' | 'rejected' | 'conflict';
    serverOrder?: number | null;
    error?: string | null;
  }>;
}

export interface PullChangesResponse {
  events: Array<ClientChangeEvent & {
    serverOrder: number;
    acceptedAt: string;
    actorUserId?: string | null;
    actorDeviceId?: string | null;
  }>;
  nextCursor: {
    scope: {
      scope: 'global' | 'workspace';
      workspaceId?: string | null;
    };
    replicaId: string;
    lastServerOrder: number;
  };
  hasMore: boolean;
}

export function registerReplica(input: RegisterReplicaRequest) {
  return apiRequest<RegisterReplicaResponse>('/sync/replicas', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function listReplicas() {
  return apiRequest<ReplicaListResponse>('/sync/replicas');
}

export function getSyncStatus(replicaId?: string | null) {
  const query = replicaId ? `?replicaId=${encodeURIComponent(replicaId)}` : '';
  const path = `/sync/status${query}`;
  return apiRequest<SyncStatusResponse>(path);
}

export function pushChanges(input: {
  replicaId: string;
  workspaceId?: string | null;
  accessEpoch?: number | null;
  events: ClientChangeEvent[];
}) {
  return apiRequest<PushChangesResponse>('/sync/push', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function pullChanges(input: {
  replicaId: string;
  scope?: 'global' | 'workspace';
  workspaceId?: string | null;
  lastServerOrder?: number;
  limit?: number;
}) {
  const params = new URLSearchParams();
  params.set('replicaId', input.replicaId);
  params.set('scope', input.scope || 'global');
  if (input.workspaceId) params.set('workspaceId', input.workspaceId);
  if (input.lastServerOrder !== undefined) params.set('lastServerOrder', String(input.lastServerOrder));
  if (input.limit !== undefined) params.set('limit', String(input.limit));
  const path = `/sync/pull?${params.toString()}`;
  return apiRequest<PullChangesResponse>(path);
}
