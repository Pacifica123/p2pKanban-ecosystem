/**
 * The phone's QR meeting end to end over a mockRelay in mockMemory. The other side
 * (a node) is played with the same rendezvous/1 functions the vectors check,
 * so this covers the phone's order of steps and what it stores.
 */
import { generateSecretKey, getPublicKey, type Event } from 'nostr-tools/pure';

import { b64url, KEYRING, makeEntry, foldRing, type KeyringItem } from './protocol';
import { confirmCode, mailboxEvents, newQr, openMailbox, qrEncode, sessionId, sponsorReview, verifyWelcome, type Qr } from './rendezvous';

const MOCK_RELAYS = ['wss://a.example', 'wss://b.example'];
const mockMemory = new Map<string, unknown>();
const mockRelay: Event[] = [];
const mockCapabilities: any[] = [];
let mockPhoneKey = generateSecretKey();

jest.mock('expo-crypto', () => ({ getRandomBytes: (n: number) => crypto.getRandomValues(new Uint8Array(n)) }));
jest.mock('../../shared/errorReport/journal', () => ({ trace: () => undefined }));
jest.mock('../../shared/errorReport/collect', () => ({ mobileSoftware: () => ({ direction: 'mobile', version: '2.1.0', build: '30', commit: null }) }));
jest.mock('../../shared/storage/storage', () => ({
  readSessionJson: async (key: string, fallback: unknown) => (mockMemory.has(key) ? JSON.parse(JSON.stringify(mockMemory.get(key))) : fallback),
  writeSessionJson: async (key: string, value: unknown) => { mockMemory.set(key, JSON.parse(JSON.stringify(value))); },
  loadStoredSession: async () => ({ user: { id: 'user-1' } }),
  loadCachedWorkspaces: async () => (mockMemory.get('workspaces') as unknown[] | undefined) ?? [],
  saveCachedWorkspaces: async (items: unknown[]) => { mockMemory.set('workspaces', items); },
  loadCachedBoards: async (space: string) => (mockMemory.get(`boards/${space}`) as unknown[] | undefined) ?? [],
  saveCachedBoards: async (space: string, items: unknown[]) => { mockMemory.set(`boards/${space}`, items); },
}));
jest.mock('../roaming/storage', () => ({
  getOrCreateRoamingDeviceSecret: async () => mockPhoneKey,
  listRoamingCapabilities: async () => mockCapabilities,
  loadRoamingCatalogChannel: async () => ({ relays: MOCK_RELAYS }),
}));
jest.mock('../roaming/service', () => ({ installRoamingCapability: async (c: unknown) => { mockCapabilities.push(c); } }));
jest.mock('../roaming/nostrRelay', () => {
  const matches = (e: Event, f: any) => (!f.kinds || f.kinds.includes(e.kind))
    && (!f['#d'] || e.tags.some(t => t[0] === 'd' && f['#d'].includes(t[1])))
    && (!f['#s'] || e.tags.some(t => t[0] === 's' && f['#s'].includes(t[1])));
  return {
    fetchTagged: async (_relays: string[], filter: unknown) => ({ events: mockRelay.filter(e => matches(e, filter)) }),
    publishEach: async (relays: string[], event: Event) => {
      if (event.kind >= 30000 && event.kind < 40000) {
        const d = event.tags.find(t => t[0] === 'd')?.[1];
        const old = mockRelay.findIndex(e => e.kind === event.kind && e.pubkey === event.pubkey && e.tags.find(t => t[0] === 'd')?.[1] === d);
        if (old >= 0) mockRelay.splice(old, 1);
      }
      mockRelay.push(event);
      return { accepted: relays, failed: [], errors: [] };
    },
  };
});

// eslint-disable-next-line import/first
import * as ring from './service';
// eslint-disable-next-line import/first
import { resetRingWritersForTests } from './writers';

const random = (n: number) => crypto.getRandomValues(new Uint8Array(n));
const now = () => Math.floor(Date.now() / 1000);
const post = (key: Uint8Array, qr: Qr, secret: Uint8Array, message: unknown) => {
  for (const e of mailboxEvents(key, secret, message, now(), qr.x, random)) mockRelay.push(e);
};
const mails = (qr: Qr, secret: Uint8Array) =>
  openMailbox(mockRelay.filter(e => e.kind === 1991 && e.tags.some(t => t[0] === 's' && t[1] === sessionId(secret))), secret);
const software = { direction: 'web', version: '2.1.0', protocols: ['p2p-kanban-account-ring/1', 'p2p-kanban-keyring/1', 'p2p-kanban-rendezvous/1', 'p2p-kanban-roaming/1'] };

/** A node with its own ring of one and one board in the keyring. */
function node() {
  const key = generateSecretKey();
  const genesis = makeEntry(key, { type: 'genesis', parents: [], nonce: b64url(random(16)),
    device: { publicKey: getPublicKey(key), name: 'Ноутбук', kind: 'web', role: 'admin' }, relays: { urls: MOCK_RELAYS, minAcks: 2 } }, now() - 60);
  const items: KeyringItem[] = [
    { kind: 'space', id: 'space-1', name: 'Дом', deleted: false, rev: 1, updatedBy: getPublicKey(key) },
    { kind: 'board', id: 'board-1', spaceId: 'space-1', name: 'Ремонт', deleted: false, rev: 1, updatedBy: getPublicKey(key),
      roaming: { protocol: 'p2p-kanban-roaming/1', epoch: 1, boardKey: b64url(random(32)) } },
  ];
  return { key, pub: getPublicKey(key), entries: [genesis], items };
}

beforeEach(() => {
  mockMemory.clear();
  mockRelay.length = 0;
  mockCapabilities.length = 0;
  mockPhoneKey = generateSecretKey();
  resetRingWritersForTests();
});

describe('invite QR: the phone joins the node ring', () => {
  it('says hello, takes the welcome, installs the board and answers ack', async () => {
    const laptop = node();
    const { qr, secret } = newQr('invite', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now(), random);
    const meeting = await ring.beginMeeting(qrEncode(qr));
    expect(meeting.role).toBe('joiner');
    const code = await ring.sayHello(meeting);
    expect(await ring.joinerPoll(meeting)).toEqual({ step: 'waiting' });

    const state = foldRing(laptop.entries, laptop.entries[0]!.id);
    const review = sponsorReview(qr, mails(qr, secret), laptop.pub, state, true, now());
    if (!('hello' in review) || !review.hello) throw new Error('no hello');
    const phone = review.hello.device.publicKey;
    expect(phone).toBe(getPublicKey(mockPhoneKey));
    expect(confirmCode(sessionId(secret), phone)).toBe(code);

    const add = makeEntry(laptop.key, { type: 'add', accountId: state.accountId, parents: state.heads, via: 'rendezvous',
      device: { ...review.hello.device, role: 'admin' } }, now());
    const entries = [...laptop.entries, add];
    post(laptop.key, qr, secret, { type: 'welcome', sessionId: sessionId(secret), accountId: state.accountId, entries,
      keyring: { protocol: KEYRING, accountId: state.accountId, ringHeads: [add.id], items: laptop.items } });

    expect(await ring.joinerPoll(meeting)).toEqual({ step: 'done', members: 2, peerName: 'Ноутбук' });
    expect(mails(qr, secret).some(m => m.sender === phone && m.message.type === 'ack')).toBe(true);
    const view = await ring.loadRing();
    expect(view.state?.accountId).toBe(state.accountId);
    expect(view.state?.members.map(m => m.name).sort()).toEqual(['Ноутбук', review.hello.device.name].sort());
    expect(mockCapabilities).toHaveLength(1);
    expect(mockCapabilities[0]).toMatchObject({ boardId: 'board-1', workspaceId: 'space-1', writerPublicKeys: expect.arrayContaining([laptop.pub, phone]) });
    expect((mockMemory.get('workspaces') as { id: string; name: string }[]).map(w => w.name)).toEqual(['Дом']);
    expect(mockMemory.get('ring/writers')).toEqual(expect.arrayContaining([laptop.pub, phone]));
    // The phone published its sealed copies under the account tag.
    expect(mockRelay.filter(e => e.pubkey === phone && e.kind >= 31990 && e.kind <= 31992)).toHaveLength(3);
  });

  it('refuses a welcome that does not come from the QR', async () => {
    const laptop = node();
    const stranger = node();
    const { qr, secret } = newQr('invite', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now(), random);
    const meeting = await ring.beginMeeting(qrEncode(qr));
    await ring.sayHello(meeting);
    post(stranger.key, qr, secret, { type: 'welcome', sessionId: sessionId(secret), accountId: stranger.entries[0]!.id,
      entries: stranger.entries, keyring: { protocol: KEYRING, accountId: stranger.entries[0]!.id, ringHeads: [], items: [] } });
    const step = await ring.joinerPoll(meeting);
    expect(step).toMatchObject({ step: 'refused', by: 'me', refusal: { reason: 'welcome-invalid' } });
    expect((await ring.loadRing()).stored).toBeNull();
  });
});

describe('join QR: the phone adds the node to its ring', () => {
  it('confirms the hello, sends a welcome the node accepts and sees the ack', async () => {
    await ring.createRing('Телефон');
    const laptop = node();
    const { qr, secret } = newQr('join', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now(), random);
    post(laptop.key, qr, secret, { type: 'hello', sessionId: sessionId(secret),
      device: { publicKey: laptop.pub, name: 'Ноутбук', kind: 'web' }, software, ring: { accountId: laptop.entries[0]!.id, members: 1 } });

    const meeting = await ring.beginMeeting(qrEncode(qr));
    expect(meeting.role).toBe('sponsor');
    const confirm = await ring.sponsorPoll(meeting);
    if (confirm.step !== 'confirm') throw new Error(`expected confirm, got ${JSON.stringify(confirm)}`);
    expect(confirm.code).toBe(confirmCode(sessionId(secret), laptop.pub));
    expect(confirm.alreadyMember).toBe(false);

    expect(await ring.sponsorConfirm(meeting, confirm.hello, 'member')).toEqual({ step: 'welcomed' });
    const welcome = mails(qr, secret).find(m => m.message.type === 'welcome')!;
    const checked = verifyWelcome(welcome, qr, laptop.pub);
    if (!('state' in checked)) throw new Error(checked.refusal.detail);
    expect(checked.state.members.find(m => m.publicKey === laptop.pub)?.role).toBe('member');

    expect(await ring.sponsorAwaitAck(meeting, laptop.pub)).toEqual({ step: 'welcomed' });
    post(laptop.key, qr, secret, { type: 'ack', sessionId: sessionId(secret), accountId: checked.state.accountId, heads: checked.state.heads });
    expect(await ring.sponsorAwaitAck(meeting, laptop.pub)).toEqual({ step: 'done', members: 2, peerName: 'Ноутбук' });
  });

  it('a second confirm of a member does not write another add', async () => {
    await ring.createRing('Телефон');
    const laptop = node();
    for (const round of [1, 2]) {
      const { qr, secret } = newQr('join', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now(), random);
      post(laptop.key, qr, secret, { type: 'hello', sessionId: sessionId(secret),
        device: { publicKey: laptop.pub, name: 'Ноутбук', kind: 'web' }, software, ring: null });
      const meeting = await ring.beginMeeting(qrEncode(qr));
      const confirm = await ring.sponsorPoll(meeting);
      if (confirm.step !== 'confirm') throw new Error('expected confirm');
      expect(confirm.alreadyMember).toBe(round === 2);
      await ring.sponsorConfirm(meeting, confirm.hello, 'admin');
    }
    expect((await ring.loadRing()).stored?.entries).toHaveLength(2);
  });

  it('ignores a hello from anyone but the device that showed the QR', async () => {
    await ring.createRing('Телефон');
    const laptop = node();
    const other = node();
    const { qr, secret } = newQr('join', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now(), random);
    const meeting = await ring.beginMeeting(qrEncode(qr));
    const hello = (device: ReturnType<typeof node>) => post(device.key, qr, secret, { type: 'hello', sessionId: sessionId(secret),
      device: { publicKey: device.pub, name: 'Подмена', kind: 'web' }, software, ring: null });
    hello(other);
    expect(await ring.sponsorPoll(meeting)).toEqual({ step: 'waiting' });
    hello(laptop);
    expect(await ring.sponsorPoll(meeting)).toMatchObject({ step: 'confirm', code: confirmCode(sessionId(secret), laptop.pub) });
  });

  it('without a ring the phone cannot sponsor', async () => {
    const laptop = node();
    const { qr } = newQr('join', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now(), random);
    const meeting = await ring.beginMeeting(qrEncode(qr));
    expect(await ring.sponsorPoll(meeting)).toMatchObject({ step: 'refused', refusal: { reason: 'sponsor-not-admin' } });
  });
});

describe('beginMeeting', () => {
  it('rejects an expired QR and the phone’s own key', async () => {
    const laptop = node();
    const expired = newQr('invite', laptop.pub, 'Ноутбук', 'web', MOCK_RELAYS, now() - 3600, random).qr;
    await expect(ring.beginMeeting(qrEncode(expired))).rejects.toThrow('Срок');
    const own = newQr('invite', getPublicKey(mockPhoneKey), 'Я', 'android', MOCK_RELAYS, now(), random).qr;
    await expect(ring.beginMeeting(qrEncode(own))).rejects.toThrow('этого же телефона');
  });
});
