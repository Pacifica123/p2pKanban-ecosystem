/**
 * Account ring of devices: p2p-kanban-account-ring/1 and p2p-kanban-keyring/1.
 *
 * Pure protocol code that follows contracts/account-ring/1/SPEC.md and
 * contracts/keyring/1/SPEC.md. The executable reference is
 * tools/ecosystem/contract_ref.py; protocol.test.ts requires the same
 * results for every published vector.
 */
import { xchacha20poly1305 } from '@noble/ciphers/chacha.js';
import { schnorr } from '@noble/curves/secp256k1.js';
import { hmac } from '@noble/hashes/hmac.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, hexToBytes, utf8ToBytes } from '@noble/hashes/utils.js';
import { decrypt as nip44Decrypt, encrypt as nip44Encrypt, getConversationKey } from 'nostr-tools/nip44';
import { finalizeEvent, verifyEvent, type Event } from 'nostr-tools/pure';

import { roamingBase64 } from '../roaming/codec';

export const RING = 'p2p-kanban-account-ring/1';
export const KEYRING = 'p2p-kanban-keyring/1';
export const RENDEZVOUS = 'p2p-kanban-rendezvous/1';
export const ROAMING = 'p2p-kanban-roaming/1';
export const RING_PROTOCOLS = [RING, KEYRING, RENDEZVOUS] as const;
export const KIND_RING_ENTRY = 27790;
export const KIND_SEALED = { 'ring-log': 31990, keyring: 31991, presence: 31992 } as const;
export type SealedType = keyof typeof KIND_SEALED;
export const MAX_ENTRIES = 1024;
export const MAX_ENTRY_CONTENT = 16 * 1024;
export const MAX_PARENTS = 16;
export const MAX_RECIPIENTS = 64;
const ENTRY_TYPES = ['genesis', 'add', 'remove', 'rename', 'relays'];

export type DeviceKind = 'web' | 'android' | 'arch';
export type Role = 'admin' | 'member';
export interface Member {
  publicKey: string;
  name: string;
  kind: DeviceKind;
  role: Role;
  addedBy: string | null;
  addEntry: string;
}
export interface RingRelays { urls: string[]; minAcks: number }
export interface RingState {
  accountId: string;
  accountTag: string;
  members: Member[];
  removed: { publicKey: string; removeEntry: string }[];
  relays: RingRelays | null;
  heads: string[];
  order: string[];
  rejected: { id: string; reason: string }[];
  pending: { id: string; missing: string[] }[];
  unknown: { id: string; type: string }[];
  readerOutdated: string[];
}
export interface KeyringItem {
  kind: string;
  id: string;
  rev: number;
  updatedBy: string;
  deleted: boolean;
  name?: string;
  spaceId?: string;
  roaming?: { protocol: string; epoch: number; boardKey: string };
  [extra: string]: unknown;
}
export interface Keyring { protocol: string; accountId: string; ringHeads: string[]; items: KeyringItem[] }
export interface Presence {
  protocol: string;
  type: 'presence';
  accountId: string;
  publicKey: string;
  seenAt: number;
  software: { direction: string; version: string; protocols: string[] };
  ringHeads: string[];
  keyring: { digest: string; items: number; boards: number } | null;
  relays: { url: string; reachable: boolean }[];
  boards?: { boardId: string; keyEpoch: number; baseline: boolean }[];
}

const b64 = roamingBase64;
export const b64url = (bytes: Uint8Array) => b64.encode(bytes);
export function unb64url(text: string) {
  if (text.includes('=')) throw new Error('base64url без «=» ожидается');
  return b64.decode(text);
}
const isHex64 = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const charCount = (text: string) => [...text].length;

/** Canonical JSON: sorted keys, no whitespace, UTF-8 as is. */
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().filter(k => object[k] !== undefined)
      .map(k => `${JSON.stringify(k)}:${canonical(object[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export const sha256Hex = (text: string) => bytesToHex(sha256(utf8ToBytes(text)));

export function accountTag(accountId: string) {
  return b64url(hmac(sha256, hexToBytes(accountId), utf8ToBytes('p2p-kanban:account-tag:v1')));
}

/** Copy without nostr-tools' cached verification flag. */
function plain(event: Event): Event {
  const { id, pubkey, created_at, kind, tags, content, sig } = event;
  return { id, pubkey, created_at, kind, tags, content, sig };
}

export function signEvent(secretKey: Uint8Array, kind: number, content: string, createdAt: number, tags: string[][] = []) {
  return plain(finalizeEvent({ kind, created_at: createdAt, tags, content }, secretKey));
}

/** Sign a ring entry (kind 27790, no tags). `protocol` is added when absent. */
export function makeEntry(secretKey: Uint8Array, body: Record<string, unknown>, createdAt: number) {
  return signEvent(secretKey, KIND_RING_ENTRY, canonical({ protocol: RING, ...body }), createdAt);
}

function verifyRaw(raw: unknown, kind: number): string | null {
  if (!raw || typeof raw !== 'object') return 'malformed-event';
  const event = raw as Partial<Event>;
  if (event.kind !== kind) return 'kind' in event ? 'wrong-kind' : 'malformed-event';
  if (typeof event.id !== 'string' || typeof event.pubkey !== 'string' || typeof event.sig !== 'string'
    || typeof event.content !== 'string' || !Array.isArray(event.tags) || !Number.isSafeInteger(event.created_at)) return 'malformed-event';
  const copy = plain(event as Event);
  const serialized = JSON.stringify([0, copy.pubkey, copy.created_at, copy.kind, copy.tags, copy.content]);
  if (bytesToHex(sha256(utf8ToBytes(serialized))) !== copy.id) return 'bad-id';
  try {
    if (!schnorr.verify(hexToBytes(copy.sig), hexToBytes(copy.id), hexToBytes(copy.pubkey))) return 'bad-signature';
  } catch { return 'bad-signature'; }
  return null;
}

/** Signature check of any event, without mutating it. */
export function eventValid(raw: unknown, kind: number) {
  return verifyRaw(raw, kind) === null;
}

type Content = Record<string, any>;

function parseEntry(raw: unknown): [Event, Content] | string {
  const reason = verifyRaw(raw, KIND_RING_ENTRY);
  if (reason) return reason;
  const event = raw as Event;
  if (utf8ToBytes(event.content).length > MAX_ENTRY_CONTENT) return 'too-large';
  let content: unknown;
  try { content = JSON.parse(event.content); } catch { return 'malformed-content'; }
  if (!content || typeof content !== 'object' || Array.isArray(content) || typeof (content as Content).type !== 'string') return 'malformed-content';
  const c = content as Content;
  if (c.protocol !== RING) return 'foreign-protocol';
  const parents = c.parents;
  if (!Array.isArray(parents) || parents.length > MAX_PARENTS || new Set(parents).size !== parents.length) return 'bad-parents';
  if ((c.type === 'genesis') !== (parents.length === 0)) return 'bad-parents';
  return [event, c];
}

function deviceOk(device: unknown) {
  const d = device as Content | null;
  if (!d || typeof d !== 'object' || !isHex64(d.publicKey)) return false;
  try { schnorr.utils.lift_x(BigInt(`0x${d.publicKey}`)); } catch { return false; }
  return typeof d.name === 'string' && charCount(d.name) >= 1 && charCount(d.name) <= 64
    && ['web', 'android', 'arch'].includes(d.kind) && ['admin', 'member'].includes(d.role);
}

function relaysOk(relays: unknown) {
  const r = relays as Content | null;
  if (!r || typeof r !== 'object' || !Array.isArray(r.urls)) return false;
  const urls = r.urls as unknown[];
  return urls.length >= 1 && urls.length <= 16 && new Set(urls).size === urls.length
    && urls.every(u => typeof u === 'string' && u.startsWith('wss://') && charCount(u) <= 256)
    && Number.isInteger(r.minAcks) && r.minAcks >= 1 && r.minAcks <= urls.length;
}

class State {
  members = new Map<string, Member>();
  removed = new Map<string, string>();
  relays: RingRelays | null = null;
  admins() { return [...this.members.values()].filter(m => m.role === 'admin').map(m => m.publicKey); }
}

const record = (d: Content, addedBy: string | null, entry: string): Member =>
  ({ publicKey: d.publicKey, name: d.name, kind: d.kind, role: d.role, addedBy, addEntry: entry });

function apply(state: State, c: Content, signer: string, id: string) {
  switch (c.type) {
    case 'genesis': state.members.set(c.device.publicKey, record(c.device, null, id)); state.relays = c.relays; break;
    case 'add': {
      const key = c.device.publicKey;
      if (!state.removed.has(key) && !state.members.has(key)) state.members.set(key, record(c.device, signer, id));
      break;
    }
    case 'remove':
      if (!state.removed.has(c.publicKey)) state.removed.set(c.publicKey, id);
      state.members.delete(c.publicKey);
      break;
    case 'rename': { const m = state.members.get(c.publicKey); if (m) m.name = c.name; break; }
    case 'relays': state.relays = c.relays; break;
    default: break;
  }
}

function authorize(past: State, c: Content, signer: string): string | null {
  if (c.type === 'genesis') return 'duplicate-genesis';
  const member = past.members.get(signer);
  if (!member) return past.removed.has(signer) ? 'signer-removed' : 'signer-not-member';
  const admin = member.role === 'admin';
  switch (c.type) {
    case 'add': {
      if (!admin) return 'signer-not-admin';
      if (!deviceOk(c.device) || !['rendezvous', 'migration'].includes(c.via)) return 'malformed-content';
      const target = c.device.publicKey;
      if (past.removed.has(target)) return 'key-was-removed';
      if (past.members.has(target)) return 'already-member';
      return null;
    }
    case 'remove': {
      if (!past.members.has(c.publicKey)) return 'unknown-target';
      if (!admin && c.publicKey !== signer) return 'signer-not-admin';
      const admins = past.admins();
      if (admins.length === 1 && admins[0] === c.publicKey) return 'last-admin';
      return null;
    }
    case 'rename': {
      if (!past.members.has(c.publicKey)) return 'unknown-target';
      if (!admin && c.publicKey !== signer) return 'signer-not-admin';
      return typeof c.name === 'string' && charCount(c.name) >= 1 && charCount(c.name) <= 64 ? null : 'malformed-content';
    }
    case 'relays':
      if (!admin) return 'signer-not-admin';
      return relaysOk(c.relays) ? null : 'malformed-content';
    default: return null;
  }
}

const byString = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** Fold the ring log into state. Input order does not matter. */
export function foldRing(entries: unknown[], accountId?: string | null): RingState {
  if (entries.length > MAX_ENTRIES) throw new Error('журнал кольца длиннее 1024 записей');
  const rejected = new Map<string, string>();
  const outdated = new Set<string>();
  const parsed = new Map<string, [Event, Content]>();
  for (const raw of entries) {
    const id = raw && typeof raw === 'object' && typeof (raw as Event).id === 'string' ? (raw as Event).id : undefined;
    if (id !== undefined && parsed.has(id)) continue;
    const result = parseEntry(raw);
    if (typeof result === 'string') {
      if (result === 'foreign-protocol') {
        try {
          const protocol = JSON.parse((raw as Event).content).protocol;
          if (typeof protocol === 'string' && protocol.startsWith('p2p-kanban-account-ring/')) outdated.add(`protocol:${protocol}`);
        } catch { /* not JSON */ }
      }
      rejected.set(String(id ?? 'None'), result);
      continue;
    }
    parsed.set(result[0].id, result);
  }
  const geneses = [...parsed].filter(([, [, c]]) => c.type === 'genesis').map(([id]) => id).sort(byString);
  const genesis = accountId != null ? (geneses.includes(accountId) ? accountId : null) : geneses.length === 1 ? geneses[0]! : null;
  if (!genesis) throw new Error('в журнале нет единственного genesis этого аккаунта');
  const [gEvent, g] = parsed.get(genesis)!;
  if (!deviceOk(g.device) || g.device.role !== 'admin' || g.device.publicKey !== gEvent.pubkey || !relaysOk(g.relays)
    || typeof g.nonce !== 'string' || g.nonce.length < 22) throw new Error('genesis некорректен');
  for (const [id, [, c]] of [...parsed]) {
    if (id !== genesis && (c.type === 'genesis' || c.accountId !== genesis)) {
      rejected.set(id, c.type === 'genesis' ? 'duplicate-genesis' : 'foreign-account');
      parsed.delete(id);
    }
  }
  const pending = new Map<string, string[]>();
  for (let changed = true; changed;) {
    changed = false;
    for (const [id, [, c]] of [...parsed]) {
      const missing = (c.parents as string[]).filter(p => !parsed.has(p));
      if (missing.length) { pending.set(id, missing.sort(byString)); parsed.delete(id); changed = true; }
    }
  }
  const children = new Map<string, string[]>([...parsed.keys()].map(id => [id, []]));
  const indegree = new Map<string, number>();
  for (const [id, [, c]] of parsed) {
    indegree.set(id, c.parents.length);
    for (const p of c.parents as string[]) children.get(p)!.push(id);
  }
  let ready = [...indegree].filter(([, d]) => d === 0).map(([id]) => id).sort(byString);
  const order: string[] = [];
  while (ready.length) {
    const id = ready.shift()!;
    order.push(id);
    for (const child of children.get(id)!) {
      const d = indegree.get(child)! - 1;
      indegree.set(child, d);
      if (d === 0) ready.push(child);
    }
    ready = ready.sort(byString);
  }
  const position = new Map(order.map((id, i) => [id, i]));
  const ancestors = new Map<string, Set<string>>();
  for (const id of order) {
    const acc = new Set<string>();
    for (const p of parsed.get(id)![1].parents as string[]) { acc.add(p); for (const a of ancestors.get(p)!) acc.add(a); }
    ancestors.set(id, acc);
  }
  const pastState = (id: string, valid: Set<string>) => {
    const state = new State();
    for (const a of [...ancestors.get(id)!].filter(x => valid.has(x)).sort((x, y) => position.get(x)! - position.get(y)!)) {
      const [ev, c] = parsed.get(a)!;
      apply(state, c, ev.pubkey, a);
    }
    return state;
  };
  const run = (frozen: Set<string>, forced: Set<string>) => {
    const valid = new Set<string>();
    const reasons = new Map<string, string>();
    for (const id of order) {
      const [ev, c] = parsed.get(id)!;
      if (id === genesis) { valid.add(id); continue; }
      if (frozen.has(id)) { reasons.set(id, 'frozen-by-remove'); continue; }
      if (forced.has(id)) { valid.add(id); continue; }
      const why = authorize(pastState(id, valid), c, ev.pubkey);
      if (why) reasons.set(id, why); else valid.add(id);
    }
    return { valid, reasons };
  };
  const phaseA = run(new Set(), new Set()).valid;
  const removes = [...phaseA].filter(id => parsed.get(id)![1].type === 'remove');
  const frozen = new Set<string>();
  for (const id of phaseA) {
    const [ev, c] = parsed.get(id)!;
    if (c.type === 'remove' || c.type === 'genesis') continue;
    const against = removes.filter(r => parsed.get(r)![1].publicKey === ev.pubkey);
    if (against.length && !against.some(r => ancestors.get(r)!.has(id))) frozen.add(id);
  }
  const { valid, reasons } = run(frozen, new Set(removes));
  const final = new State();
  const unknown: { id: string; type: string }[] = [];
  for (const id of order) {
    if (!valid.has(id)) continue;
    const [ev, c] = parsed.get(id)!;
    apply(final, c, ev.pubkey, id);
    if (!ENTRY_TYPES.includes(c.type)) { unknown.push({ id, type: c.type }); outdated.add(`type:${c.type}`); }
  }
  for (const [id, why] of reasons) rejected.set(id, why);
  const referenced = new Set(order.flatMap(id => parsed.get(id)![1].parents as string[]));
  return {
    accountId: genesis,
    accountTag: accountTag(genesis),
    members: [...final.members.values()].sort((a, b) => byString(a.publicKey, b.publicKey)),
    removed: [...final.removed].sort(([a], [b]) => byString(a, b)).map(([publicKey, removeEntry]) => ({ publicKey, removeEntry })),
    relays: final.relays,
    heads: order.filter(id => !referenced.has(id)).sort(byString),
    order,
    rejected: [...rejected].sort(([a], [b]) => byString(a, b)).map(([id, reason]) => ({ id, reason })),
    pending: [...pending].sort(([a], [b]) => byString(a, b)).map(([id, missing]) => ({ id, missing })),
    unknown,
    readerOutdated: [...outdated].sort(byString),
  };
}

/** Which presences lag: unknown ring protocols or an old view of the log. */
export function presenceSkew(presences: Presence[], ringHeads: string[]) {
  const heads = [...ringHeads].sort(byString).join(',');
  return [...presences].sort((a, b) => byString(a.publicKey, b.publicKey)).flatMap(p => {
    const known = new Set(p.software?.protocols ?? []);
    const missingProtocols = RING_PROTOCOLS.filter(proto => !known.has(proto));
    const staleRing = [...(p.ringHeads ?? [])].sort(byString).join(',') !== heads;
    return missingProtocols.length || staleRing ? [{ publicKey: p.publicKey, missingProtocols, staleRing }] : [];
  });
}

// ---------------------------------------------------------------- keyring

function itemRank(item: KeyringItem): [number, number, string] {
  const epoch = item.roaming && typeof item.roaming === 'object' && Number.isInteger(item.roaming.epoch) ? item.roaming.epoch : 0;
  return [epoch, Number.isInteger(item.rev) ? item.rev : 0, sha256Hex(canonical(item))];
}

const rankGreater = (a: [number, number, string], b: [number, number, string]) =>
  a[0] !== b[0] ? a[0] > b[0] : a[1] !== b[1] ? a[1] > b[1] : a[2] > b[2];

/** Merge keyring copies: (epoch, rev, sha256) wins; deletion is irreversible. */
export function mergeKeyrings(copies: { items?: KeyringItem[] }[]): KeyringItem[] {
  const best = new Map<string, KeyringItem>();
  const deleted = new Set<string>();
  // Python's tuple order of (kind, id) is the code-point order of both strings.
  const keyOf = (item: KeyringItem) => JSON.stringify([item.kind, item.id]);
  for (const copy of copies) {
    for (const item of copy.items ?? []) {
      const key = keyOf(item);
      if (item.deleted === true) deleted.add(key);
      const current = best.get(key);
      if (!current || rankGreater(itemRank(item), itemRank(current))) best.set(key, item);
    }
  }
  return [...best.values()]
    .sort((a, b) => byString(a.kind, b.kind) || byString(a.id, b.id))
    .map(item => {
      if (!deleted.has(keyOf(item)) || item.deleted === true) return item;
      const { roaming: _dropped, ...rest } = item;
      return { ...rest, deleted: true } as KeyringItem;
    });
}

export function keyringDigest(items: KeyringItem[]) {
  return sha256Hex(canonical([...items].sort((a, b) => byString(a.kind, b.kind) || byString(a.id, b.id))));
}

export function keyringSummary(items: KeyringItem[]) {
  return { digest: keyringDigest(items), items: items.length, boards: items.filter(i => i.kind === 'board' && i.deleted !== true).length };
}

// ---------------------------------------------------------------- sealed records

const sealAad = (type: string, tag: string) => utf8ToBytes(`p2p-kanban:seal:v1|${type}|${tag}`);

export function seal(secretKey: Uint8Array, recipients: string[], type: SealedType, tag: string, plaintext: unknown,
  random: (n: number) => Uint8Array) {
  const unique = [...new Set(recipients)].sort(byString);
  if (unique.length < 1 || unique.length > MAX_RECIPIENTS) throw new Error('1..64 получателей');
  const cek = random(32);
  const nonce = random(24);
  const ciphertext = xchacha20poly1305(cek, nonce, sealAad(type, tag)).encrypt(utf8ToBytes(canonical(plaintext)));
  const wrapped = unique.map(pk => nip44Encrypt(b64url(cek), getConversationKey(secretKey, pk))).sort(byString);
  return { version: 1, type, nonce: b64url(nonce), ciphertext: b64url(ciphertext), recipients: wrapped };
}

export function unseal(secretKey: Uint8Array, sender: string, tag: string, sealed: Content) {
  const conversation = getConversationKey(secretKey, sender);
  for (const wrapped of Array.isArray(sealed.recipients) ? sealed.recipients : []) {
    let cek: Uint8Array;
    try { cek = unb64url(nip44Decrypt(wrapped, conversation)); } catch { continue; }
    const plainBytes = xchacha20poly1305(cek, unb64url(sealed.nonce), sealAad(sealed.type, tag)).decrypt(unb64url(sealed.ciphertext));
    return JSON.parse(new TextDecoder().decode(plainBytes));
  }
  throw new Error('запись запечатана не для этого устройства');
}

export function sealedEvent(secretKey: Uint8Array, type: SealedType, accountId: string, recipients: string[], plaintext: unknown,
  createdAt: number, random: (n: number) => Uint8Array) {
  const tag = accountTag(accountId);
  const content = seal(secretKey, recipients, type, tag, plaintext, random);
  return signEvent(secretKey, KIND_SEALED[type], canonical(content), createdAt, [['d', tag], ['t', 'p2pkanban-ring'], ['v', '1']]);
}

/** Verify and open a sealed event fetched from a relay. Throws when not for us. */
export function openSealedEvent(secretKey: Uint8Array, raw: Event, accountId: string): { sender: string; type: SealedType; plain: any } {
  const reason = verifyRaw(raw, raw?.kind);
  if (reason) throw new Error(reason);
  const tag = accountTag(accountId);
  if (!raw.tags.some(t => t[0] === 'd' && t[1] === tag)) throw new Error('событие другого аккаунта');
  const sealed = JSON.parse(raw.content) as Content;
  const type = sealed.type as SealedType;
  if (KIND_SEALED[type] !== raw.kind) throw new Error('kind не совпадает с типом записи');
  return { sender: raw.pubkey, type, plain: unseal(secretKey, raw.pubkey, tag, sealed) };
}

export { verifyEvent };
