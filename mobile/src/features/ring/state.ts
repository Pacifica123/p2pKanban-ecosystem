/**
 * The phone's copy of its ring (R3): pure rules for what it keeps and publishes.
 * Storage and relays live in service.ts.
 */
import type { Event } from 'nostr-tools/pure';

import {
  canonical, foldRing, KEYRING, mergeKeyrings, RING, MAX_ENTRIES,
  type Keyring, type KeyringItem, type Presence, type RingState,
} from './protocol';

export interface SyncReport {
  at: number;
  relays: { url: string; reachable: boolean }[];
  minAcks: number;
  quorum: boolean;
  fetched: number;
  newEntries: number;
  keyringCopies: number;
  presences: number;
  installedBoards: number;
  errors: string[];
}

export interface StoredRing {
  accountId: string;
  entries: Event[];
  /** This phone's own keyring copy, as published. */
  own: KeyringItem[];
  /** Latest keyring copy of every other member. */
  copies: Record<string, { createdAt: number; keyring: Keyring }>;
  presences: Record<string, Presence>;
  lastSync: SyncReport | null;
}

export interface Opened { sender: string; type: string; plain: any; createdAt: number }

const keyOf = (item: Pick<KeyringItem, 'kind' | 'id'>) => `${item.kind}|${item.id}`;
const rankFree = ({ rev: _rev, updatedBy: _by, ...rest }: KeyringItem) => canonical(rest);

/**
 * The phone's next own copy. A changed item gets rev above every rev seen in
 * the ring; an item that already equals the ring's winner is not repeated.
 * Nothing is deleted from here: a phone whose cache lost a board must not
 * delete it for the whole ring (deletion with key rotation is R5).
 */
/** A keyring item as the phone sees it now, before rev and updatedBy. */
export type ItemDraft = Pick<KeyringItem, 'kind' | 'id' | 'deleted' | 'name' | 'spaceId' | 'roaming'> & Record<string, unknown>;

export function nextOwnItems(stored: KeyringItem[], current: ItemDraft[], merged: KeyringItem[], me: string) {
  const own = new Map(stored.map(item => [keyOf(item), item]));
  const winners = new Map(merged.map(item => [keyOf(item), item]));
  for (const now of current) {
    const key = keyOf(now);
    const old = own.get(key);
    const winner = winners.get(key);
    const draft = { ...now, rev: 0, updatedBy: me } as KeyringItem;
    if (old && rankFree(old) === rankFree(draft)) continue;
    if (!old && winner && rankFree(winner) === rankFree(draft)) continue;
    if (winner?.deleted === true) continue;
    const rev = Math.max(old?.rev ?? 0, winner?.rev ?? 0) + 1;
    own.set(key, { ...draft, rev });
  }
  return [...own.values()].sort((a, b) => (keyOf(a) < keyOf(b) ? -1 : 1));
}

/** Everything the phone knows of the keyring: its own copy and the others'. */
export function mergedItems(stored: StoredRing) {
  return mergeKeyrings([{ items: stored.own }, ...Object.values(stored.copies).map(c => c.keyring)]);
}

export function foldStored(stored: StoredRing): RingState {
  return foldRing(stored.entries, stored.accountId);
}

/**
 * Take in sealed copies fetched under the account tag. Entries carry their own
 * signatures, so a ring-log copy counts whoever sealed it; keyrings and
 * presences only from members of the resulting ring.
 */
export function absorb(stored: StoredRing, opened: Opened[], me: string) {
  const known = new Set(stored.entries.map(e => e.id));
  const candidates = new Map<string, Event>();
  for (const item of opened) {
    if (item.sender === me || item.plain?.accountId !== stored.accountId) continue;
    if (item.type === 'ring-log' && item.plain.protocol === RING && Array.isArray(item.plain.entries)) {
      for (const entry of item.plain.entries.slice(0, MAX_ENTRIES)) {
        if (entry && typeof entry.id === 'string' && !known.has(entry.id)) candidates.set(entry.id, entry);
      }
    }
  }
  let entries = stored.entries;
  let newEntries = 0;
  if (candidates.size) {
    const all = [...stored.entries, ...candidates.values()];
    const folded = foldRing(all, stored.accountId);
    const rejected = new Set(folded.rejected.map(r => r.id));
    const accepted = [...candidates.values()].filter(e => !rejected.has(e.id)).slice(0, MAX_ENTRIES - stored.entries.length);
    entries = [...stored.entries, ...accepted];
    newEntries = accepted.length;
  }
  const state = foldRing(entries, stored.accountId);
  const members = new Set(state.members.map(m => m.publicKey));
  const copies = { ...stored.copies };
  const presences = { ...stored.presences };
  let keyringCopies = 0;
  let presenceCount = 0;
  for (const item of opened) {
    if (item.sender === me || !members.has(item.sender) || item.plain?.accountId !== stored.accountId) continue;
    if (item.type === 'keyring' && item.plain.protocol === KEYRING && Array.isArray(item.plain.items)) {
      if ((copies[item.sender]?.createdAt ?? -1) < item.createdAt) {
        copies[item.sender] = { createdAt: item.createdAt, keyring: item.plain };
        keyringCopies += 1;
      }
    }
    if (item.type === 'presence' && item.plain.type === 'presence' && item.plain.publicKey === item.sender) {
      if ((presences[item.sender]?.seenAt ?? -1) < item.plain.seenAt) {
        presences[item.sender] = item.plain;
        presenceCount += 1;
      }
    }
  }
  // A removed member's copies stop counting.
  for (const key of Object.keys(copies)) if (!members.has(key)) delete copies[key];
  for (const key of Object.keys(presences)) if (!members.has(key)) delete presences[key];
  return { stored: { ...stored, entries, copies, presences }, state, newEntries, keyringCopies, presences: presenceCount };
}

/** Boards of the keyring this phone should install: unknown here or in a newer epoch. */
export function boardsToInstall(merged: KeyringItem[], installed: Map<string, number>) {
  return merged.filter(item => item.kind === 'board' && item.deleted !== true && item.roaming
    && typeof item.spaceId === 'string' && (installed.get(item.id) ?? 0) < item.roaming.epoch);
}
