import type { ClientChangeEvent, PullChangesResponse, Replica } from '@/features/sync/api/sync';

const REPLICA_KEY = 'p2p-planner.sync.replica.v1';
const REPLICA_CLIENT_KEY = 'p2p-planner.sync.replica-key.v1';
const REPLICA_SEQ_KEY = 'p2p-planner.sync.replica-seq.v1';
const CURSORS_KEY = 'p2p-planner.sync.cursors.v1';
const PENDING_EVENTS_KEY = 'p2p-planner.sync.pending-events.v1';

function storage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage || null;
  } catch {
    return null;
  }
}

function readJson<T>(key: string, fallback: T): T {
  const currentStorage = storage();
  if (!currentStorage) return fallback;
  try {
    const raw = currentStorage.getItem(key);
    return raw ? JSON.parse(raw) as T : fallback;
  } catch {
    return fallback;
  }
}

function writeJson<T>(key: string, value: T) {
  const currentStorage = storage();
  if (!currentStorage) return;
  currentStorage.setItem(key, JSON.stringify(value));
}

function randomId(prefix: string) {
  const raw = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `${prefix}${raw}`;
}

export function getOrCreateClientReplicaKey() {
  const currentStorage = storage();
  if (!currentStorage) return randomId('browser-');
  const existing = currentStorage.getItem(REPLICA_CLIENT_KEY);
  if (existing) return existing;
  const next = randomId('browser-');
  currentStorage.setItem(REPLICA_CLIENT_KEY, next);
  return next;
}

export function loadRegisteredReplica() {
  return readJson<Replica | null>(REPLICA_KEY, null);
}

export function saveRegisteredReplica(replica: Replica) {
  writeJson(REPLICA_KEY, replica);
}

export function nextReplicaSeq() {
  const currentStorage = storage();
  if (!currentStorage) return 1;
  const current = Number(currentStorage.getItem(REPLICA_SEQ_KEY) || '0');
  const next = Number.isFinite(current) ? current + 1 : 1;
  currentStorage.setItem(REPLICA_SEQ_KEY, String(next));
  return next;
}

export function loadSyncCursors() {
  return readJson<Record<string, number>>(CURSORS_KEY, {});
}

export function saveSyncCursor(scopeKey: string, lastServerOrder: number) {
  writeJson(CURSORS_KEY, {
    ...loadSyncCursors(),
    [scopeKey]: Math.max(loadSyncCursors()[scopeKey] || 0, lastServerOrder),
  });
}

export function workspaceScopeKey(workspaceId?: string | null) {
  return workspaceId ? `workspace:${workspaceId}` : 'global';
}

export function saveCursorFromPull(response: PullChangesResponse) {
  const workspaceId = response.nextCursor.scope.workspaceId;
  const scopeKey = response.nextCursor.scope.scope === 'workspace' ? workspaceScopeKey(workspaceId) : 'global';
  saveSyncCursor(scopeKey, response.nextCursor.lastServerOrder);
}

export function loadPendingSyncEvents() {
  return readJson<ClientChangeEvent[]>(PENDING_EVENTS_KEY, []);
}

export function appendPendingSyncEvent(event: ClientChangeEvent) {
  writeJson(PENDING_EVENTS_KEY, [...loadPendingSyncEvents(), event]);
}

export function removePendingSyncEvents(eventIds: string[]) {
  const remove = new Set(eventIds);
  writeJson(PENDING_EVENTS_KEY, loadPendingSyncEvents().filter((event) => !remove.has(event.eventId)));
}

export function createSyncEventId() {
  return randomId('').replace(/^[^0-9a-f]*/i, '') || randomId('');
}
