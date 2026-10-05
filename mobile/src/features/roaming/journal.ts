import AsyncStorage from '@react-native-async-storage/async-storage';
import { sessionStorageKey } from '../../shared/storage/storage';
import type { LocalBoardSnapshot } from '../localFirst/model';
import { applyRoamingEvents, EMPTY_ROAMING_APPLY_STATE } from './merge';
import type { RoamingBoardEvent, RoamingCapability } from './types';

// One durable record: an inbox cannot advance beyond its materialized state.
// Keep events (including our own) to replay late prerequisites in clock order.
export interface ReplicaJournal {
  epoch: number;
  seed: LocalBoardSnapshot | null;
  events: RoamingBoardEvent[];
  pending: string[];
  clock: number;
  wire?: Record<string, import("nostr-tools/pure").Event>;
}

let writes = Promise.resolve<unknown>(undefined);
export function serializeReplica<T>(task: () => Promise<T>): Promise<T> {
  const run = writes.then(task, task);
  writes = run.then(() => undefined, () => undefined);
  return run;
}

function key(boardId: string) { return sessionStorageKey(`roaming/journal-v2/${boardId}`); }

export async function loadJournal(cap: RoamingCapability, seed: LocalBoardSnapshot | null) {
  const raw = await AsyncStorage.getItem(key(cap.boardId));
  if (raw) {
    const value = JSON.parse(raw) as ReplicaJournal;
    if (value.epoch === cap.capabilityEpoch) return {...value,seed:value.seed || seed};
  }
  return { epoch: cap.capabilityEpoch, seed, events: [], pending: [], clock: 0 } satisfies ReplicaJournal;
}

export function mergeJournal(journal: ReplicaJournal, incoming: RoamingBoardEvent[]) {
  const events = new Map(journal.events.map(event => [event.eventId, event]));
  for (const event of incoming) if (!events.has(event.eventId)) events.set(event.eventId, event);
  return {
    ...journal,
    events: [...events.values()],
    clock: incoming.reduce((clock, event) => {
      const versions = event.payload.fieldVersions;
      const stamps = versions && typeof versions === 'object' ? Object.values(versions) : [];
      return stamps.reduce<number>((value, stamp) => {
        const candidate = (stamp as {logicalClock?:number})?.logicalClock;
        return Number.isSafeInteger(candidate) ? Math.max(value, candidate!) : value;
      }, Math.max(clock, event.logicalClock));
    }, journal.clock),
  };
}

export function projectJournal(journal: ReplicaJournal) {
  return applyRoamingEvents(journal.seed, EMPTY_ROAMING_APPLY_STATE, journal.events);
}

export async function saveJournal(boardId: string, journal: ReplicaJournal) {
  await AsyncStorage.setItem(key(boardId), JSON.stringify(journal));
}
