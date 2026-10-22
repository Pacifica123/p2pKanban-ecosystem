/**
 * The device ring on the phone (R3) and adding a device by QR (R4).
 *
 * The phone keeps a full copy of its ring log and keyring, exchanges sealed
 * copies and presences with the ring's relays, and installs boards other
 * members published, so their content arrives by roaming/1 without a node.
 * Meetings: the phone always scans. An `invite` QR makes the phone the joiner,
 * a `join` QR makes it the sponsor that adds the shown device.
 */
import * as Crypto from 'expo-crypto';
import { Platform } from 'react-native';
import { generateSecretKey, getPublicKey, type Event } from 'nostr-tools/pure';

import type { Board, Workspace } from '../../shared/types/api';
import { trace } from '../../shared/errorReport/journal';
import { mobileSoftware } from '../../shared/errorReport/collect';
import {
  loadCachedBoards, loadCachedWorkspaces, loadStoredSession, readSessionJson, saveCachedBoards, saveCachedWorkspaces,
  writeSessionJson,
} from '../../shared/storage/storage';
import { decodeBoardKey, deriveBoardTag } from '../roaming/codec';
import { fetchTagged, publishEach } from '../roaming/nostrRelay';
import { installRoamingCapability } from '../roaming/service';
import { getOrCreateRoamingDeviceSecret, listRoamingCapabilities, loadRoamingCatalogChannel } from '../roaming/storage';
import { ROAMING_CAPABILITY_VERSION, ROAMING_PROTOCOL_VERSION, type RoamingCapability } from '../roaming/types';
import {
  accountTag, b64url, KEYRING, KIND_SEALED, keyringSummary, makeEntry, mergeKeyrings, openSealedEvent, presenceSkew,
  RENDEZVOUS, RING, ROAMING, sealedEvent, unb64url,
  type DeviceKind, type KeyringItem, type Presence, type RingState, type Role,
} from './protocol';
import {
  confirmCode, mailboxEvents, openMailbox, qrDecode, refuseMessage, sessionId, sponsorReview, verifyWelcome,
  type Mail, type Qr, type Refusal,
} from './rendezvous';
import { absorb, boardsToInstall, foldStored, mergedItems, nextOwnItems, type ItemDraft, type Opened, type StoredRing, type SyncReport } from './state';
import { saveRingWriters } from './writers';

export const PROTOCOLS = [RING, KEYRING, RENDEZVOUS, ROAMING];
/** roaming/1 board events: the node's event kind 1978 + 1. */
const DEFAULT_ROAMING_KIND = 1979;
const STORE = 'ring/state';
const NAME = 'ring/device-name';
const random = (n: number) => Crypto.getRandomBytes(n);
const now = () => Math.floor(Date.now() / 1000);

const secret = () => getOrCreateRoamingDeviceSecret(generateSecretKey);
export async function devicePublicKey() { return getPublicKey(await secret()); }

export async function deviceName() {
  const stored = await readSessionJson<string | null>(NAME, null);
  if (stored) return stored;
  const model = (Platform.constants as { Model?: string } | undefined)?.Model;
  return [...(model ? `Телефон ${model}` : 'Телефон')].slice(0, 64).join('');
}
export async function saveDeviceName(name: string) {
  const clean = [...name.trim()].slice(0, 64).join('');
  if (!clean) throw new Error('Имя устройства не может быть пустым.');
  await writeSessionJson(NAME, clean);
}

export interface RingView {
  me: string;
  stored: StoredRing | null;
  state: RingState | null;
  items: KeyringItem[];
  skew: ReturnType<typeof presenceSkew>;
}

export async function loadRing(): Promise<RingView> {
  const me = await devicePublicKey();
  const stored = await readSessionJson<StoredRing | null>(STORE, null);
  if (!stored) return { me, stored: null, state: null, items: [], skew: [] };
  const state = foldStored(stored);
  return { me, stored, state, items: mergedItems(stored), skew: presenceSkew(Object.values(stored.presences), state.heads) };
}

async function save(stored: StoredRing, state: RingState) {
  await writeSessionJson(STORE, stored);
  await saveRingWriters(state.members.map(m => m.publicKey));
}

/** wss:// relays this phone already knows from its node: the starting set of a ring made here. */
async function knownRelays() {
  const channel = await loadRoamingCatalogChannel();
  const fromBoards = (await listRoamingCapabilities()).flatMap(c => c.relays);
  return [...new Set([...(channel?.relays ?? []), ...fromBoards])].filter(r => r.startsWith('wss://')).slice(0, 16);
}

export async function createRing(name: string) {
  const current = await loadRing();
  if (current.stored) throw new Error('Кольцо на этом телефоне уже есть.');
  const urls = await knownRelays();
  if (!urls.length) {
    throw new Error('Телефон ещё не знает ни одного relay wss://. Войдите в кольцо узла по QR или откройте доску в сети узла.');
  }
  await saveDeviceName(name);
  const key = await secret();
  const genesis = makeEntry(key, { type: 'genesis', parents: [], nonce: b64url(random(16)),
    device: { publicKey: getPublicKey(key), name: await deviceName(), kind: 'android', role: 'admin' },
    relays: { urls, minAcks: Math.min(2, urls.length) } }, now());
  const stored: StoredRing = { accountId: genesis.id, entries: [genesis], own: [], copies: {}, presences: {}, lastSync: null };
  await save(stored, foldStored(stored));
  trace('ring', () => `создано кольцо ${genesis.id.slice(0, 12)}`);
  return syncRing();
}

/** What this phone holds: cached spaces and installed boards, without rev. */
async function currentItems() {
  const items: ItemDraft[] = [];
  const workspaces = await loadCachedWorkspaces();
  for (const w of workspaces) if (!w.isArchived) items.push({ kind: 'space', id: w.id, name: [...w.name].slice(0, 200).join(''), deleted: false });
  for (const c of await listRoamingCapabilities()) {
    const board = (await loadCachedBoards(c.workspaceId)).find(b => b.id === c.boardId);
    if (!board) continue;
    items.push({ kind: 'board', id: c.boardId, spaceId: c.workspaceId, name: [...board.name].slice(0, 200).join(''), deleted: false,
      roaming: { protocol: ROAMING, epoch: c.capabilityEpoch, boardKey: c.boardKey } });
  }
  return items;
}

/** Install boards (and their spaces) other members put in the keyring. */
async function installFromKeyring(merged: KeyringItem[], state: RingState) {
  const installed = await listRoamingCapabilities();
  const epochs = new Map(installed.map(c => [c.boardId, c.capabilityEpoch]));
  const plan = boardsToInstall(merged, epochs);
  if (!plan.length) return { installed: 0, errors: [] as string[] };
  const ringRelays = state.relays?.urls ?? [];
  const relays = [...new Set([...ringRelays, ...installed.flatMap(c => c.relays), ...(await knownRelays())])].slice(0, 16);
  const eventKind = installed[0]?.eventKind ?? DEFAULT_ROAMING_KIND;
  const members = state.members.map(m => m.publicKey);
  const session = await loadStoredSession();
  const owner = session?.user.id ?? '';
  const spaces = new Map(merged.filter(i => i.kind === 'space' && i.deleted !== true).map(i => [i.id, i]));
  const workspaces = new Map((await loadCachedWorkspaces()).map(w => [w.id, w]));
  const at = new Date().toISOString();
  const errors: string[] = [];
  let count = 0;
  for (const item of plan) {
    const roaming = item.roaming!;
    try {
      const capability: RoamingCapability = {
        formatVersion: ROAMING_CAPABILITY_VERSION, protocolVersion: ROAMING_PROTOCOL_VERSION,
        workspaceId: item.spaceId!, boardId: item.id, boardKey: roaming.boardKey,
        boardTag: deriveBoardTag(decodeBoardKey(roaming.boardKey), item.id),
        capabilityEpoch: roaming.epoch, canWrite: true, writerPublicKeys: members,
        relays, eventKind, minimumRelayAcks: Math.min(state.relays?.minAcks ?? 1, relays.length), provisionedAt: at,
      };
      await installRoamingCapability(capability);
      if (!workspaces.has(item.spaceId!)) {
        const space = spaces.get(item.spaceId!);
        const workspace: Workspace = { id: item.spaceId!, name: space?.name ?? 'Пространство', visibility: 'private', ownerUserId: owner,
          currentUserRole: 'owner', isArchived: false, createdAt: at, updatedAt: at, accessEpoch: roaming.epoch };
        workspaces.set(workspace.id, workspace);
      }
      const boards = await loadCachedBoards(item.spaceId!);
      if (!boards.some(b => b.id === item.id)) {
        const board: Board = { id: item.id, workspaceId: item.spaceId!, name: item.name ?? 'Доска', boardType: 'kanban',
          isArchived: false, createdAt: at, updatedAt: at };
        await saveCachedBoards(item.spaceId!, [...boards, board]);
      }
      count += 1;
    } catch (error) {
      errors.push(`доска «${item.name ?? item.id}»: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  // Empty spaces travel too.
  for (const space of spaces.values()) {
    if (!workspaces.has(space.id)) workspaces.set(space.id, { id: space.id, name: space.name ?? 'Пространство', visibility: 'private',
      ownerUserId: owner, currentUserRole: 'owner', isArchived: false, createdAt: at, updatedAt: at, accessEpoch: 1 });
  }
  await saveCachedWorkspaces([...workspaces.values()].sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id)));
  trace('ring', () => `из связки установлено досок: ${count}${errors.length ? `; ${errors.join('; ')}` : ''}`);
  return { installed: count, errors };
}

/** Publish own sealed log, keyring and presence; take in the others'. */
export async function syncRing(): Promise<RingView> {
  const view = await loadRing();
  if (!view.stored || !view.state) throw new Error('На этом телефоне ещё нет кольца.');
  const key = await secret();
  const me = view.me;
  let stored = view.stored;
  let state = view.state;
  if (!state.members.some(m => m.publicKey === me)) throw new Error('Этот телефон исключён из кольца.');
  const relays = state.relays?.urls ?? [];
  const minAcks = state.relays?.minAcks ?? 1;
  const errors: string[] = [];
  // Own keyring first, so the copy we publish is current.
  stored = { ...stored, own: nextOwnItems(stored.own, await currentItems(), mergedItems(stored), me) };
  const recipients = state.members.map(m => m.publicKey).slice(0, 64);
  const at = now();
  const published: { type: string; accepted: string[] }[] = [];
  const publish = async (event: Event, type: string) => {
    const result = await publishEach(relays, event);
    published.push({ type, accepted: result.accepted });
    errors.push(...result.errors.map(e => `${type}: ${e}`));
    return result.accepted;
  };
  await publish(sealedEvent(key, 'ring-log', stored.accountId, recipients, { protocol: RING, accountId: stored.accountId, entries: stored.entries }, at, random), 'ring-log');
  await publish(sealedEvent(key, 'keyring', stored.accountId, recipients,
    { protocol: KEYRING, accountId: stored.accountId, ringHeads: state.heads, items: stored.own }, at, random), 'keyring');
  let fetched = 0;
  const opened: Opened[] = [];
  try {
    const response = await fetchTagged(relays, { kinds: Object.values(KIND_SEALED), '#d': [accountTag(stored.accountId)] });
    fetched = response.events.length;
    for (const event of response.events) {
      try { opened.push({ ...openSealedEvent(key, event, stored.accountId), createdAt: event.created_at }); }
      catch { /* sealed for others or tampered */ }
    }
  } catch (error) { errors.push(`чтение: ${error instanceof Error ? error.message : String(error)}`); }
  const taken = absorb(stored, opened, me);
  stored = taken.stored;
  state = taken.state;
  const merged = mergedItems(stored);
  const install = await installFromKeyring(merged, state);
  errors.push(...install.errors);
  const reachable = new Set(published.flatMap(p => p.accepted));
  const presence: Presence = {
    protocol: RING, type: 'presence', accountId: stored.accountId, publicKey: me, seenAt: now(),
    software: { direction: 'mobile', version: mobileSoftware().version, protocols: PROTOCOLS },
    ringHeads: state.heads.slice(0, 16), keyring: keyringSummary(merged),
    relays: relays.map(url => ({ url, reachable: reachable.has(url) })),
  };
  await publish(sealedEvent(key, 'presence', stored.accountId, state.members.map(m => m.publicKey).slice(0, 64), presence, now(), random), 'presence');
  const report: SyncReport = {
    at: now(), relays: presence.relays, minAcks, quorum: published.length > 0 && published.every(p => p.accepted.length >= minAcks),
    fetched, newEntries: taken.newEntries, keyringCopies: taken.keyringCopies, presences: taken.presences,
    installedBoards: install.installed, errors,
  };
  stored = { ...stored, lastSync: report };
  await save(stored, state);
  trace('ring', () => `обмен кольца: кворум ${report.quorum ? 'собран' : 'не собран'}, получено ${fetched}, новых записей ${taken.newEntries}`);
  return loadRing();
}

// ---------------------------------------------------------------- meeting by QR

export interface Meeting {
  qr: Qr;
  secret: Uint8Array;
  session: string;
  /** The phone's part: it joins on an invite QR and sponsors a join QR. */
  role: 'joiner' | 'sponsor';
  me: string;
}

export type MeetingStep =
  | { step: 'waiting' }
  | { step: 'confirm'; hello: any; code: string; alreadyMember: boolean }
  | { step: 'welcomed' }
  | { step: 'done'; members: number; peerName: string }
  | { step: 'refused'; by: 'peer' | 'me'; refusal: Refusal };

export async function beginMeeting(text: string): Promise<Meeting> {
  const qr = qrDecode(text);
  if (qr.x < now()) throw new Error('Срок этого QR истёк: попросите показать новый.');
  const me = await devicePublicKey();
  if (qr.k === me) throw new Error('Это QR этого же телефона.');
  const secretBytes = unb64url(qr.s);
  return { qr, secret: secretBytes, session: sessionId(secretBytes), role: qr.m === 'invite' ? 'joiner' : 'sponsor', me };
}

async function mailbox(meeting: Meeting): Promise<Mail[]> {
  const { events } = await fetchTagged(meeting.qr.r, { kinds: [1991], '#s': [meeting.session] });
  return openMailbox(events, meeting.secret);
}

async function send(meeting: Meeting, message: unknown) {
  const events = mailboxEvents(await secret(), meeting.secret, message, now(), meeting.qr.x, random);
  for (const event of events) {
    const result = await publishEach(meeting.qr.r, event);
    if (!result.accepted.length) throw new Error(`Ни один relay встречи не принял сообщение. ${result.errors.join('; ')}`);
  }
}

/** Joiner (invite QR): say hello at once and show the code. */
export async function sayHello(meeting: Meeting) {
  const view = await loadRing();
  const ring = view.state ? { accountId: view.state.accountId, members: view.state.members.length } : null;
  await send(meeting, { type: 'hello', sessionId: meeting.session,
    device: { publicKey: meeting.me, name: await deviceName(), kind: 'android' as DeviceKind },
    software: { direction: 'mobile', version: mobileSoftware().version, protocols: PROTOCOLS }, ring });
  return confirmCode(meeting.session, meeting.me);
}

const peerRefusal = (mails: Mail[], me: string): MeetingStep | null => {
  const refuse = mails.find(m => m.sender !== me && m.message.type === 'refuse');
  return refuse ? { step: 'refused', by: 'peer', refusal: { reason: String(refuse.message.reason), detail: String(refuse.message.detail ?? '') } } : null;
};

async function refuse(meeting: Meeting, refusal: Refusal): Promise<MeetingStep> {
  try { await send(meeting, refuseMessage(meeting.session, refusal)); }
  catch (error) { trace('ring', () => `отказ встречи не отправлен: ${error instanceof Error ? error.message : String(error)}`); }
  return { step: 'refused', by: 'me', refusal };
}

/** Joiner: wait for welcome, check it, adopt the ring, answer ack. */
export async function joinerPoll(meeting: Meeting): Promise<MeetingStep> {
  const mails = await mailbox(meeting);
  const refused = peerRefusal(mails, meeting.me);
  if (refused) return refused;
  const welcomes = mails.filter(m => m.sender !== meeting.me && m.message.type === 'welcome');
  if (!welcomes.length) return now() > meeting.qr.x ? { step: 'refused', by: 'me', refusal: { reason: 'expired', detail: 'Срок QR истёк.' } } : { step: 'waiting' };
  const welcome = welcomes.at(-1)!;
  const checked = verifyWelcome(welcome, meeting.qr, meeting.me);
  if ('refusal' in checked) return refuse(meeting, checked.refusal);
  const state = checked.state;
  const current = await loadRing();
  if (current.state && current.state.accountId !== state.accountId && current.state.members.length > 1) {
    return refuse(meeting, { reason: 'ring-merge-unsupported',
      detail: `Этот телефон уже в другом кольце из ${current.state.members.length} устройств. Слияние колец пока не поддерживается.` });
  }
  const same = current.stored?.accountId === state.accountId ? current.stored : null;
  const known = new Set((same?.entries ?? []).map(e => e.id));
  const stored: StoredRing = {
    accountId: state.accountId,
    entries: [...(same?.entries ?? []), ...(welcome.message.entries as Event[]).filter(e => !known.has(e.id))],
    own: same?.own ?? [],
    copies: { ...(same?.copies ?? {}), [welcome.sender]: { createdAt: welcome.createdAt, keyring: welcome.message.keyring } },
    presences: same?.presences ?? {},
    lastSync: same?.lastSync ?? null,
  };
  await save(stored, foldStored(stored));
  await send(meeting, { type: 'ack', sessionId: meeting.session, accountId: state.accountId, heads: state.heads.slice(0, 16) });
  const sponsor = state.members.find(m => m.publicKey === welcome.sender);
  try { await syncRing(); } catch (error) { trace('ring', () => `первый обмен после входа: ${error instanceof Error ? error.message : String(error)}`); }
  return { step: 'done', members: state.members.length, peerName: sponsor?.name ?? 'узел' };
}

/** Sponsor (join QR): the hello to confirm, or a refusal sent to the joiner. */
export async function sponsorPoll(meeting: Meeting): Promise<MeetingStep> {
  const view = await loadRing();
  if (!view.state) {
    return { step: 'refused', by: 'me', refusal: { reason: 'sponsor-not-admin',
      detail: 'На этом телефоне ещё нет кольца. Создайте его на экране «Кольцо устройств» или войдите в кольцо узла.' } };
  }
  const mails = await mailbox(meeting);
  const refused = peerRefusal(mails, meeting.me);
  if (refused) return refused;
  const fresh = view.state.readerOutdated.length === 0;
  const review = sponsorReview(meeting.qr, mails, meeting.me, view.state, fresh, now());
  if ('refusal' in review) return refuse(meeting, review.refusal);
  if (!review.hello) return { step: 'waiting' };
  const joiner = review.hello.device.publicKey;
  return { step: 'confirm', hello: review.hello, code: confirmCode(meeting.session, joiner),
    alreadyMember: view.state.members.some(m => m.publicKey === joiner) };
}

/** Sponsor: the person compared the codes. Write add, send welcome, publish. */
export async function sponsorConfirm(meeting: Meeting, hello: any, role: Role): Promise<MeetingStep> {
  const view = await loadRing();
  if (!view.stored || !view.state) throw new Error('На этом телефоне нет кольца.');
  const key = await secret();
  let stored = view.stored;
  const joiner = hello.device.publicKey as string;
  if (!view.state.members.some(m => m.publicKey === joiner)) {
    const add = makeEntry(key, { type: 'add', accountId: stored.accountId, parents: view.state.heads.slice(0, 16), via: 'rendezvous',
      device: { publicKey: joiner, name: hello.device.name, kind: hello.device.kind, role } }, now());
    const next = { ...stored, entries: [...stored.entries, add] };
    const folded = foldStored(next);
    const rejected = folded.rejected.find(r => r.id === add.id);
    if (rejected) throw new Error(`Запись add отклонена свёрткой: ${rejected.reason}`);
    stored = next;
  }
  stored = { ...stored, own: nextOwnItems(stored.own, await currentItems(), mergedItems(stored), meeting.me) };
  const state = foldStored(stored);
  await save(stored, state);
  await send(meeting, { type: 'welcome', sessionId: meeting.session, accountId: stored.accountId, entries: stored.entries,
    keyring: { protocol: KEYRING, accountId: stored.accountId, ringHeads: state.heads, items: mergeKeyrings([{ items: stored.own },
      ...Object.values(stored.copies).map(c => c.keyring)]) } });
  try { await syncRing(); } catch (error) { trace('ring', () => `обмен после добавления: ${error instanceof Error ? error.message : String(error)}`); }
  return { step: 'welcomed' };
}

/** Sponsor: the joiner acknowledged. */
export async function sponsorAwaitAck(meeting: Meeting, joiner: string): Promise<MeetingStep> {
  const mails = await mailbox(meeting);
  const refused = peerRefusal(mails, meeting.me);
  if (refused) return refused;
  if (!mails.some(m => m.sender === joiner && m.message.type === 'ack')) return { step: 'welcomed' };
  const view = await loadRing();
  return { step: 'done', members: view.state?.members.length ?? 0, peerName: view.state?.members.find(m => m.publicKey === joiner)?.name ?? 'устройство' };
}

export async function declineMeeting(meeting: Meeting) {
  return refuse(meeting, { reason: 'declined', detail: 'Человек отклонил добавление на телефоне.' });
}
