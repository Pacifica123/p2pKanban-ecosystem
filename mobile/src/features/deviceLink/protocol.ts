import {
  finalizeEvent,
  getPublicKey,
  serializeEvent,
  verifyEvent,
  type Event,
  type EventTemplate,
} from 'nostr-tools/pure';
import { encrypt, decrypt, getConversationKey } from 'nostr-tools/nip44';
import { schnorr } from '@noble/curves/secp256k1.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils.js';
import { roamingBase64 } from '../roaming/codec';
import { throwIfCanceled, UI_SLICE_MS, yieldToUi } from '../../shared/lib/uiBudget';
export const LINK_PROTOCOL = 'p2p-kanban-device-link/2',
  GRANT_KIND = 27780,
  REQUEST_KIND = 27781,
  RESPONSE_KIND = 27782;
const now = () => Math.floor(Date.now() / 1000);
export interface Grant {
  protocol: string;
  workspaceId: string;
  boardId: string;
  userId: string;
  epoch: number;
  subject: string;
  canDelegate: boolean;
  parentId: string | null;
  expiresAt: number;
}
export function checkEvent(raw: Event, kind: number) {
  // Avoid nostr-tools' cached verification flag on a mutated in-memory object.
  const e = JSON.parse(JSON.stringify(raw)) as Event;
  if (e.kind !== kind || !verifyEvent(e) || e.created_at > now() + 60)
    throw new Error('Неверная подпись или версия подключения.');
  return JSON.parse(e.content);
}
export function verifyChain(chain: Event[], subject: string, at = now()) {
  if (!Array.isArray(chain) || !chain.length || chain.length > 8)
    throw new Error('Неверная цепочка доверия.');
  let previous: Grant | undefined;
  for (let i = 0; i < chain.length; i++) {
    const g = checkEvent(chain[i]!, GRANT_KIND) as Grant;
    if (
      chain[i]!.created_at > at ||
      g.protocol !== LINK_PROTOCOL ||
      !Number.isSafeInteger(g.epoch) ||
      g.epoch < 1 ||
      !Number.isSafeInteger(g.expiresAt) ||
      g.expiresAt <= at ||
      !/^[a-f0-9]{64}$/.test(g.subject) ||
      typeof g.canDelegate !== 'boolean'
    )
      throw new Error('Право подключения истекло или повреждено.');
    if (previous) {
      if (
        !previous.canDelegate ||
        chain[i]!.pubkey !== previous.subject ||
        g.parentId !== chain[i - 1]!.id ||
        g.workspaceId !== previous.workspaceId ||
        g.boardId !== previous.boardId ||
        g.userId !== previous.userId ||
        g.epoch !== previous.epoch ||
        g.expiresAt > previous.expiresAt
      )
        throw new Error('Недопустимое расширение прав.');
    } else if (g.parentId !== null) throw new Error('Неверный корень доверия.');
    previous = g;
  }
  if (previous!.subject !== subject)
    throw new Error('Право выдано другому устройству.');
  return { root: chain[0]!.pubkey, grant: previous! };
}
// A valid enrollment establishes membership for the capability epoch.
// Invitation expiry still limits NEW delegation; it is not a recurring lease.
export function verifyReplicationChain(chain: Event[], subject: string, signedAt: number) {
  const enrolledAt = chain?.at(-1)?.created_at;
  if (!Number.isSafeInteger(enrolledAt) || enrolledAt! > signedAt)
    throw new Error('Событие предшествует подключению устройства.');
  return verifyChain(chain, subject, enrolledAt);
}
export function extendChain(
  secret: Uint8Array,
  chain: Event[],
  subject: string,
) {
  const { grant } = verifyChain(chain, getPublicKey(secret));
  if (!grant.canDelegate || chain.length >= 8)
    throw new Error('Нет права дальнейшего подключения.');
  return [
    ...chain,
    finalizeEvent(
      {
        kind: GRANT_KIND,
        created_at: now(),
        tags: [],
        content: JSON.stringify({
          ...grant,
          subject,
          parentId: chain[chain.length - 1]!.id,
        }),
      },
      secret,
    ),
  ];
}
export function checkRequest(raw: Event) {
  const d = checkEvent(raw, REQUEST_KIND);
  if (
    d.protocol !== LINK_PROTOCOL ||
    !Number.isSafeInteger(d.expiresAt) ||
    d.expiresAt <= now() ||
    d.expiresAt > now() + 660
  )
    throw new Error('Запрос истёк. Создайте новый на ноутбуке.');
  return {
    recipient: raw.pubkey,
    id: raw.id,
    expiresAt: d.expiresAt as number,
  };
}
export function encryptPack(
  secret: Uint8Array,
  recipient: string,
  data: unknown,
) {
  const bytes = new TextEncoder().encode(JSON.stringify(data));
  if (bytes.length > 8 * 1024 * 1024)
    throw new Error('Снимок превышает 8 MiB.');
  const key = getConversationKey(secret, recipient),
    parts: string[] = [];
  for (let i = 0; i < bytes.length; i += 24000) {
    const b = roamingBase64
      .encode(bytes.slice(i, i + 24000))
      .replace(/-/g, '+')
      .replace(/_/g, '/');
    parts.push(encrypt(b + '='.repeat((4 - (b.length % 4)) % 4), key));
  }
  return parts;
}
export function decryptPack(secret: Uint8Array, response: Event) {
  const d = checkEvent(response, RESPONSE_KIND);
  if (
    d.protocol !== LINK_PROTOCOL ||
    d.recipient !== getPublicKey(secret) ||
    !Array.isArray(d.parts) ||
    !d.parts.length ||
    d.parts.length > 350
  )
    throw new Error('Снимок адресован другому устройству.');
  const key = getConversationKey(secret, response.pubkey),
    chunks: Uint8Array[] = [];
  let length = 0;
  for (const part of d.parts) {
    if (typeof part !== 'string' || part.length > 66000)
      throw new Error('Большой фрагмент снимка.');
    const b = roamingBase64.decode(decrypt(part, key));
    length += b.length;
    if (length > 8 * 1024 * 1024) throw new Error('Снимок превышает 8 MiB.');
    chunks.push(b);
  }
  const b = new Uint8Array(length);
  let offset = 0;
  for (const c of chunks) {
    b.set(c, offset);
    offset += c.length;
  }
  return JSON.parse(new TextDecoder().decode(b));
}

export function decryptPayloadParts(secret: Uint8Array, sender: string, parts: string[]) {
  if (!parts.length || parts.length > 350) throw new Error('Неверный каталог реплик.');
  const key = getConversationKey(secret, sender), chunks: Uint8Array[] = [];
  let length = 0;
  for (const part of parts) {
    if (typeof part !== 'string' || part.length > 66000) throw new Error('Повреждён фрагмент каталога.');
    const chunk = roamingBase64.decode(decrypt(part, key));
    length += chunk.length;
    if (length > 8 * 1024 * 1024) throw new Error('Каталог реплик слишком велик.');
    chunks.push(chunk);
  }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return JSON.parse(new TextDecoder().decode(bytes));
}

/*
 * A prepared pack holds whole workspaces: megabytes of NIP-44 parts under one
 * signature. In Hermes one synchronous pass (hash + decrypt) took the JS thread
 * for tens of seconds, and taps and the back button waited behind it. The async
 * forms below do the same checks in slices and give the thread back between
 * them; a closed screen cancels them through the signal.
 */
const HASH_CHUNK = 16 * 1024;

async function sliceBreak(started: { at: number }, signal?: AbortSignal | null) {
  if (Date.now() - started.at < UI_SLICE_MS) return;
  await yieldToUi();
  throwIfCanceled(signal);
  started.at = Date.now();
}

async function eventHashSliced(event: Event | (EventTemplate & { pubkey: string }), signal?: AbortSignal | null) {
  const bytes = new TextEncoder().encode(serializeEvent(event as Event));
  const hash = sha256.create(), started = { at: Date.now() };
  for (let i = 0; i < bytes.length; i += HASH_CHUNK) {
    hash.update(bytes.subarray(i, i + HASH_CHUNK));
    await sliceBreak(started, signal);
  }
  return bytesToHex(hash.digest());
}

/** verifyEvent with the hash computed in slices. */
export async function verifyEventSliced(event: Event, signal?: AbortSignal | null) {
  let hash: string;
  try { hash = await eventHashSliced(event, signal); }
  catch (error) { if (signal?.aborted) throw error; return false; }
  if (hash !== event.id) return false;
  try { return schnorr.verify(hexToBytes(event.sig), hexToBytes(hash), hexToBytes(event.pubkey)); }
  catch { return false; }
}

/** finalizeEvent for a large content, hashed in slices. */
export async function finalizeEventSliced(template: EventTemplate, secret: Uint8Array, signal?: AbortSignal | null) {
  const event = { ...template, pubkey: getPublicKey(secret) } as Event;
  event.id = await eventHashSliced(event, signal);
  event.sig = bytesToHex(schnorr.sign(hexToBytes(event.id), secret));
  return event;
}

export async function checkEventSliced(raw: Event, kind: number, signal?: AbortSignal | null) {
  const e = JSON.parse(JSON.stringify(raw)) as Event;
  if (e.kind !== kind || e.created_at > now() + 60 || !(await verifyEventSliced(e, signal)))
    throw new Error('Неверная подпись или версия подключения.');
  return JSON.parse(e.content);
}

export async function encryptPackSliced(
  secret: Uint8Array,
  recipient: string,
  data: unknown,
  signal?: AbortSignal | null,
) {
  const bytes = new TextEncoder().encode(JSON.stringify(data));
  if (bytes.length > 8 * 1024 * 1024)
    throw new Error('Снимок превышает 8 MiB.');
  const key = getConversationKey(secret, recipient),
    parts: string[] = [];
  for (let i = 0; i < bytes.length; i += 24000) {
    throwIfCanceled(signal);
    const b = roamingBase64
      .encode(bytes.slice(i, i + 24000))
      .replace(/-/g, '+')
      .replace(/_/g, '/');
    parts.push(encrypt(b + '='.repeat((4 - (b.length % 4)) % 4), key));
    await yieldToUi();
  }
  throwIfCanceled(signal);
  return parts;
}

export async function decryptPackSliced(secret: Uint8Array, response: Event, signal?: AbortSignal | null) {
  const d = await checkEventSliced(response, RESPONSE_KIND, signal);
  if (
    d.protocol !== LINK_PROTOCOL ||
    d.recipient !== getPublicKey(secret) ||
    !Array.isArray(d.parts) ||
    !d.parts.length ||
    d.parts.length > 350
  )
    throw new Error('Снимок адресован другому устройству.');
  const key = getConversationKey(secret, response.pubkey),
    chunks: Uint8Array[] = [];
  let length = 0;
  for (const part of d.parts) {
    throwIfCanceled(signal);
    if (typeof part !== 'string' || part.length > 66000)
      throw new Error('Большой фрагмент снимка.');
    const b = roamingBase64.decode(decrypt(part, key));
    length += b.length;
    if (length > 8 * 1024 * 1024) throw new Error('Снимок превышает 8 MiB.');
    chunks.push(b);
    // One part is the smallest unit NIP-44 can open; the thread is returned after each.
    await yieldToUi();
  }
  throwIfCanceled(signal);
  const b = new Uint8Array(length);
  let offset = 0;
  for (const c of chunks) {
    b.set(c, offset);
    offset += c.length;
  }
  return JSON.parse(new TextDecoder().decode(b));
}
