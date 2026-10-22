/**
 * Adding a device by QR through a relay mailbox: p2p-kanban-rendezvous/1.
 * Pure protocol code after contracts/rendezvous/1/SPEC.md; rendezvous.test.ts
 * requires the same QR, derived values and messages as every published vector.
 */
import { xchacha20poly1305 } from '@noble/ciphers/chacha.js';
import { hkdf } from '@noble/hashes/hkdf.js';
import { hmac } from '@noble/hashes/hmac.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { utf8ToBytes } from '@noble/hashes/utils.js';
import { getPublicKey, type Event } from 'nostr-tools/pure';

import {
  b64url, canonical, eventValid, foldRing, KEYRING, MAX_ENTRIES, RENDEZVOUS, RING, signEvent, unb64url,
  type DeviceKind, type RingState,
} from './protocol';

export const KIND_MAILBOX = 1991;
export const QR_PREFIX = 'p2pkanban:rv1:';
export const MAX_LIFETIME_SECS = 600;
export const PART_BYTES = 48 * 1024;

export type Mode = 'invite' | 'join';
export interface Qr { v: 1; m: Mode; k: string; s: string; r: string[]; n: string; t: DeviceKind; x: number }
export interface Mail { sender: string; createdAt: number; message: any }
export interface Refusal { reason: string; detail: string }

/** The scanned text is a QR of a newer contract version. */
export class NewerQrError extends Error {
  constructor() { super('QR от более новой версии приложения: обновите это устройство.'); this.name = 'NewerQrError'; }
}

export function qrEncode(qr: Qr) {
  return QR_PREFIX + b64url(utf8ToBytes(canonical(qr)));
}

export function checkQr(qr: any): asserts qr is Qr {
  const fail = (why: string) => { throw new Error(`QR встречи: ${why}.`); };
  if (!qr || qr.v !== 1) fail('другая версия');
  if (!['invite', 'join'].includes(qr.m)) fail('неизвестный режим');
  if (typeof qr.k !== 'string' || !/^[0-9a-f]{64}$/.test(qr.k)) fail('нет ключа устройства');
  let secret: Uint8Array | null = null;
  try { secret = unb64url(qr.s); } catch { /* checked below */ }
  if (!secret || secret.length !== 32) fail('секрет встречи — 32 байта');
  if (!Array.isArray(qr.r) || qr.r.length < 1 || qr.r.length > 3 || new Set(qr.r).size !== qr.r.length
    || !qr.r.every((u: unknown) => typeof u === 'string' && u.startsWith('wss://') && [...u].length <= 256)) fail('relay — от 1 до 3 адресов wss://');
  if (typeof qr.n !== 'string' || [...qr.n].length < 1 || [...qr.n].length > 64) fail('имя устройства — от 1 до 64 символов');
  if (!['web', 'android', 'arch'].includes(qr.t)) fail('неизвестный вид устройства');
  if (!Number.isSafeInteger(qr.x)) fail('нет срока действия');
}

export function qrDecode(text: string): Qr {
  const value = text.trim();
  const version = /^p2pkanban:rv(\d+):/.exec(value);
  if (version && Number(version[1]) > 1) throw new NewerQrError();
  if (!value.startsWith(QR_PREFIX)) throw new Error('Это не QR встречи p2pKanban.');
  let qr: unknown;
  try { qr = JSON.parse(new TextDecoder().decode(unb64url(value.slice(QR_PREFIX.length)))); }
  catch { throw new Error('QR встречи повреждён.'); }
  checkQr(qr);
  return qr;
}

export function newQr(mode: Mode, shower: string, name: string, kind: DeviceKind, relays: string[], now: number,
  random: (n: number) => Uint8Array, lifetime = MAX_LIFETIME_SECS) {
  const secret = random(32);
  const qr: Qr = { v: 1, m: mode, k: shower, s: b64url(secret), r: relays.filter(r => r.startsWith('wss://')).slice(0, 3),
    n: [...name].slice(0, 64).join(''), t: kind, x: now + Math.min(lifetime, MAX_LIFETIME_SECS) };
  checkQr(qr);
  return { qr, secret };
}

export const sessionId = (secret: Uint8Array) => b64url(hmac(sha256, secret, utf8ToBytes('p2p-kanban:rendezvous-id:v1')));
export const sessionKey = (secret: Uint8Array) =>
  hkdf(sha256, secret, utf8ToBytes('p2p-kanban:rendezvous:v1'), utf8ToBytes('session-key'), 32);

export function confirmCode(session: string, joiner: string) {
  const d = sha256(utf8ToBytes(`p2p-kanban:rendezvous-confirm:v1|${session}|${joiner}`));
  const n = (((d[0]! << 24) >>> 0) + (d[1]! << 16) + (d[2]! << 8) + d[3]!) % 1_000_000;
  return `${String(Math.floor(n / 1000)).padStart(3, '0')} ${String(n % 1000).padStart(3, '0')}`;
}

const aad = (session: string, sender: string, part: number, parts: number) =>
  utf8ToBytes(`p2p-kanban:rendezvous:v1|${session}|${sender}|${part}/${parts}`);

/** Signed mailbox events (kind 1991) carrying one message, in parts when large. */
export function mailboxEvents(secretKey: Uint8Array, secret: Uint8Array, message: any, createdAt: number, expiresAt: number,
  random: (n: number) => Uint8Array): Event[] {
  const session = sessionId(secret);
  if (message.sessionId !== session) throw new Error('сообщение другой встречи');
  const key = sessionKey(secret);
  const sender = getPublicKey(secretKey);
  const bytes = utf8ToBytes(canonical(message));
  const parts = Math.max(1, Math.ceil(bytes.length / PART_BYTES));
  return Array.from({ length: parts }, (_, index) => {
    const part = index + 1;
    const nonce = random(24);
    const chunk = bytes.subarray(index * PART_BYTES, (index + 1) * PART_BYTES);
    const ciphertext = xchacha20poly1305(key, nonce, aad(session, sender, part, parts)).encrypt(chunk);
    const content = canonical({ version: 1, nonce: b64url(nonce), ciphertext: b64url(ciphertext) });
    return signEvent(secretKey, KIND_MAILBOX, content, createdAt,
      [['s', session], ['t', 'p2pkanban-rendezvous'], ['part', String(part), String(parts)], ['expiration', String(expiresAt)]]);
  });
}

/** Verify, decrypt and reassemble every message of the session; the rest is skipped. */
export function openMailbox(events: Event[], secret: Uint8Array): Mail[] {
  const session = sessionId(secret);
  const key = sessionKey(secret);
  const groups = new Map<string, { sender: string; createdAt: number; parts: number; chunks: Map<number, Uint8Array> }>();
  const seen = new Set<string>();
  for (const event of events) {
    if (!event || seen.has(event.id) || !eventValid(event, KIND_MAILBOX)) continue;
    seen.add(event.id);
    const tag = (name: string) => event.tags.find(t => t[0] === name);
    if (tag('s')?.[1] !== session || tag('s')?.length !== 2) continue;
    const partTag = tag('part');
    const part = partTag ? Number(partTag[1]) : 1;
    const parts = partTag ? Number(partTag[2]) : 1;
    if (!Number.isInteger(part) || !Number.isInteger(parts) || part < 1 || part > parts || parts > 64) continue;
    try {
      const body = JSON.parse(event.content);
      if (body.version !== 1) continue;
      const nonce = unb64url(body.nonce);
      if (nonce.length !== 24) continue;
      const plainBytes = xchacha20poly1305(key, nonce, aad(session, event.pubkey, part, parts)).decrypt(unb64url(body.ciphertext));
      const groupKey = `${event.pubkey}|${event.created_at}|${parts}`;
      const group = groups.get(groupKey) ?? { sender: event.pubkey, createdAt: event.created_at, parts, chunks: new Map() };
      group.chunks.set(part, plainBytes);
      groups.set(groupKey, group);
    } catch { /* forged, foreign or broken part */ }
  }
  const mails: Mail[] = [];
  for (const group of groups.values()) {
    if (group.chunks.size !== group.parts) continue;
    const ordered = [...group.chunks].sort(([a], [b]) => a - b).map(([, bytes]) => bytes);
    const joined = new Uint8Array(ordered.reduce((n, b) => n + b.length, 0));
    let offset = 0;
    for (const bytes of ordered) { joined.set(bytes, offset); offset += bytes.length; }
    try {
      const message = JSON.parse(new TextDecoder().decode(joined));
      if (message?.sessionId === session && typeof message.type === 'string') mails.push({ sender: group.sender, createdAt: group.createdAt, message });
    } catch { /* not JSON */ }
  }
  return mails.sort((a, b) => a.createdAt - b.createdAt || (a.sender < b.sender ? -1 : a.sender > b.sender ? 1 : 0));
}

export const refuseMessage = (session: string, refusal: Refusal) =>
  ({ type: 'refuse', sessionId: session, reason: refusal.reason, detail: [...refusal.detail].slice(0, 500).join('') });

/**
 * The hello this sponsor may answer (null: nothing yet), or why it refuses.
 * `fresh`: the sponsor's keyring matches its ring heads.
 */
export function sponsorReview(qr: Qr, mails: Mail[], sponsor: string, state: Pick<RingState, 'accountId' | 'members' | 'removed'>,
  fresh: boolean, now: number): { hello: any | null } | { refusal: Refusal } {
  if (now > qr.x) return { refusal: { reason: 'expired', detail: 'Срок QR истёк (10 минут). Покажите новый код.' } };
  const joinerKey = qr.m === 'join' ? qr.k : null;
  const hellos = mails.filter(m => m.sender !== sponsor && m.message.type === 'hello'
    && (joinerKey === null || m.sender === joinerKey) && m.message.device?.publicKey === m.sender);
  if (new Set(hellos.map(m => m.sender)).size > 1) {
    return { refusal: { reason: 'contested', detail: 'В почтовый ящик пришли два разных устройства: QR мог увидеть кто-то ещё. Покажите новый код.' } };
  }
  const hello = hellos.at(-1)?.message;
  if (!hello) return { hello: null };
  const me = state.members.find(m => m.publicKey === sponsor);
  if (!me || me.role !== 'admin') return { refusal: { reason: 'sponsor-not-admin', detail: 'Добавлять устройства может только устройство кольца с ролью admin.' } };
  if (!fresh) return { refusal: { reason: 'sponsor-stale', detail: 'Связка ключей этого устройства отстаёт от журнала кольца. Синхронизируйте кольцо и повторите.' } };
  const joiner = hello.device.publicKey;
  if (state.removed.some(r => r.publicKey === joiner)) {
    return { refusal: { reason: 'key-removed', detail: 'Этот ключ устройства удалён из кольца. Удалённое устройство возвращается с новым ключом.' } };
  }
  const members = Number(hello.ring?.members ?? 0);
  if (hello.ring && members > 1 && typeof hello.ring.accountId === 'string' && hello.ring.accountId !== state.accountId) {
    return { refusal: { reason: 'ring-merge-unsupported',
      detail: `${hello.device.name ?? 'Устройство'} уже состоит в другом кольце из ${members} устройств. Слияние колец пока не поддерживается.` } };
  }
  const known: string[] = Array.isArray(hello.software?.protocols) ? hello.software.protocols : [];
  const missing = [RING, KEYRING, RENDEZVOUS].filter(p => !known.includes(p));
  if (missing.length) return { refusal: { reason: 'joiner-outdated', detail: `Входящее устройство не знает ${missing.join(', ')}: обновите его.` } };
  return { hello };
}

/** What a joiner checks in welcome before adopting the ring: the folded state, or a refusal. */
export function verifyWelcome(welcome: Mail, qr: Qr, joiner: string): { state: RingState } | { refusal: Refusal } {
  const bad = (detail: string) => ({ refusal: { reason: 'welcome-invalid', detail } });
  if (qr.m === 'invite' && qr.k !== welcome.sender) return bad('welcome подписан не тем устройством, чей QR сканировали');
  const m = welcome.message;
  if (typeof m.accountId !== 'string') return bad('в welcome нет accountId');
  if (!Array.isArray(m.entries) || !m.entries.length || m.entries.length > MAX_ENTRIES) return bad('в welcome нет журнала кольца');
  let state: RingState;
  try { state = foldRing(m.entries, m.accountId); } catch { return bad('журнал из welcome не сворачивается'); }
  if (!state.members.some(x => x.publicKey === joiner)) return bad('этого устройства нет среди участников кольца из welcome');
  if (state.members.find(x => x.publicKey === welcome.sender)?.role !== 'admin') return bad('поручитель не admin кольца из welcome');
  const k = m.keyring;
  if (!k || k.protocol !== KEYRING || k.accountId !== m.accountId || !Array.isArray(k.items)) return bad('связка ключей из welcome другого аккаунта или повреждена');
  return { state };
}
