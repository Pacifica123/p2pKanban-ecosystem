import * as Crypto from 'expo-crypto';

import {
  getSyncStatus,
  pullWorkspace,
  registerReplica,
} from '../../shared/api/endpoints';
import {
  readSessionJson,
  writeSessionJson,
} from '../../shared/storage/storage';
import type { Replica } from '../../shared/types/api';

const REPLICA_KEY = 'sync/replica';
const REPLICA_CLIENT_KEY = 'sync/replica-client-key';
const CURSORS_KEY = 'sync/cursors';

async function getOrCreateReplicaClientKey() {
  const current = await readSessionJson<string | null>(REPLICA_CLIENT_KEY, null);
  if (current) return current;
  const next = `android-${Crypto.randomUUID()}`;
  await writeSessionJson(REPLICA_CLIENT_KEY, next);
  return next;
}

export async function ensureMobileReplica() {
  const replicaKey = await getOrCreateReplicaClientKey();
  const response = await registerReplica({
    replicaKey,
    displayName: 'p2pKanban Android',
    platform: 'android',
    appVersion: '1.0.0',
  });
  await writeSessionJson(REPLICA_KEY, response.replica);
  return response.replica;
}

export async function touchWorkspaceSync(workspaceId: string) {
  const stored = await readSessionJson<Replica | null>(REPLICA_KEY, null);
  const replica = stored?.status === 'active' ? stored : await ensureMobileReplica();
  const cursors = await readSessionJson<Record<string, number>>(CURSORS_KEY, {});
  const key = `workspace:${workspaceId}`;
  const response = await pullWorkspace({
    replicaId: replica.id,
    workspaceId,
    lastServerOrder: cursors[key] || 0,
  });
  await writeSessionJson(CURSORS_KEY, {
    ...cursors,
    [key]: Math.max(cursors[key] || 0, response.nextCursor.lastServerOrder),
  });
  return getSyncStatus(replica.id);
}
