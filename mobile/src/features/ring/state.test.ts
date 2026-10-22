/** The phone's own ring rules: what it absorbs, publishes and installs. */
import { generateSecretKey, getPublicKey } from 'nostr-tools/pure';

import { b64url, KEYRING, makeEntry, RING, type KeyringItem } from './protocol';
import { absorb, boardsToInstall, foldStored, mergedItems, nextOwnItems, type Opened, type StoredRing } from './state';

const random = (n: number) => crypto.getRandomValues(new Uint8Array(n));

function ringOfTwo() {
  const phone = generateSecretKey();
  const laptop = generateSecretKey();
  const stranger = generateSecretKey();
  const genesis = makeEntry(phone, { type: 'genesis', parents: [], nonce: b64url(random(16)),
    device: { publicKey: getPublicKey(phone), name: 'Телефон', kind: 'android', role: 'admin' },
    relays: { urls: ['wss://a.example', 'wss://b.example'], minAcks: 2 } }, 1000);
  const add = makeEntry(phone, { type: 'add', accountId: genesis.id, parents: [genesis.id], via: 'rendezvous',
    device: { publicKey: getPublicKey(laptop), name: 'Ноутбук', kind: 'web', role: 'admin' } }, 1001);
  const stored: StoredRing = { accountId: genesis.id, entries: [genesis], own: [], copies: {}, presences: {}, lastSync: null };
  return { phone, laptop, stranger, genesis, add, stored, me: getPublicKey(phone) };
}

const board = (id: string, epoch: number, rest: Partial<KeyringItem> = {}): KeyringItem => ({
  kind: 'board', id, spaceId: 's1', name: id, deleted: false, rev: 1, updatedBy: 'x',
  roaming: { protocol: 'p2p-kanban-roaming/1', epoch, boardKey: 'k' }, ...rest,
});

describe('absorb', () => {
  it('takes signed entries from any copy and keyrings only from members', () => {
    const { stored, add, laptop, stranger, me } = ringOfTwo();
    const laptopKey = getPublicKey(laptop);
    const opened: Opened[] = [
      { sender: getPublicKey(stranger), type: 'ring-log', createdAt: 5, plain: { protocol: RING, accountId: stored.accountId, entries: [add] } },
      { sender: laptopKey, type: 'keyring', createdAt: 6, plain: { protocol: KEYRING, accountId: stored.accountId, ringHeads: [], items: [board('b1', 1)] } },
      { sender: getPublicKey(stranger), type: 'keyring', createdAt: 7, plain: { protocol: KEYRING, accountId: stored.accountId, ringHeads: [], items: [board('evil', 9)] } },
    ];
    const taken = absorb(stored, opened, me);
    expect(taken.newEntries).toBe(1);
    expect(taken.state.members.map(m => m.publicKey).sort()).toEqual([laptopKey, me].sort());
    expect(Object.keys(taken.stored.copies)).toEqual([laptopKey]);
    expect(mergedItems(taken.stored).map(i => i.id)).toEqual(['b1']);
  });

  it('ignores entries the fold rejects and copies of another account', () => {
    const { stored, stranger, me } = ringOfTwo();
    const forged = makeEntry(stranger, { type: 'add', accountId: stored.accountId, parents: [stored.accountId], via: 'rendezvous',
      device: { publicKey: getPublicKey(stranger), name: 'Чужой', kind: 'web', role: 'admin' } }, 1002);
    const taken = absorb(stored, [
      { sender: getPublicKey(stranger), type: 'ring-log', createdAt: 5, plain: { protocol: RING, accountId: stored.accountId, entries: [forged] } },
      { sender: getPublicKey(stranger), type: 'ring-log', createdAt: 5, plain: { protocol: RING, accountId: 'other', entries: [forged] } },
    ], me);
    expect(taken.newEntries).toBe(0);
    expect(taken.state.members).toHaveLength(1);
  });

  it('keeps only the newest copy of a member', () => {
    const { stored, add, laptop, me } = ringOfTwo();
    const laptopKey = getPublicKey(laptop);
    const base = { ...stored, entries: [...stored.entries, add] };
    const copy = (createdAt: number, id: string): Opened => ({ sender: laptopKey, type: 'keyring', createdAt,
      plain: { protocol: KEYRING, accountId: stored.accountId, ringHeads: [], items: [board(id, 1)] } });
    const taken = absorb(base, [copy(9, 'new'), copy(3, 'old')], me);
    expect(mergedItems(taken.stored).map(i => i.id)).toEqual(['new']);
  });
});

describe('nextOwnItems', () => {
  it('raises rev above the ring and does not repeat the winner', () => {
    const merged = [board('b1', 1, { rev: 4, updatedBy: 'laptop' })];
    const same = { kind: 'board', id: 'b1', spaceId: 's1', name: 'b1', deleted: false, roaming: merged[0]!.roaming };
    expect(nextOwnItems([], [same], merged, 'me')).toEqual([]);
    const renamed = nextOwnItems([], [{ ...same, name: 'Новое' }], merged, 'me');
    expect(renamed).toMatchObject([{ id: 'b1', name: 'Новое', rev: 5, updatedBy: 'me' }]);
    expect(nextOwnItems(renamed, [{ ...same, name: 'Новое' }], merged, 'me')).toEqual(renamed);
  });

  it('never deletes what the phone no longer holds and never revives a deleted item', () => {
    const own = [board('kept', 1, { updatedBy: 'me' })];
    expect(nextOwnItems(own, [], [], 'me')).toEqual(own);
    const gone = [board('b1', 1, { deleted: true, rev: 2 })];
    expect(nextOwnItems([], [{ kind: 'board', id: 'b1', deleted: false }], gone, 'me')).toEqual([]);
  });
});

describe('boardsToInstall', () => {
  it('installs unknown boards and newer epochs only', () => {
    const merged = [board('new', 1), board('same', 2), board('newer', 3), board('dead', 1, { deleted: true }),
      { kind: 'space', id: 's1', deleted: false, rev: 1, updatedBy: 'x' } as KeyringItem];
    const installed = new Map([['same', 2], ['newer', 2]]);
    expect(boardsToInstall(merged, installed).map(i => i.id)).toEqual(['new', 'newer']);
  });
});

describe('foldStored', () => {
  it('folds the stored log', () => {
    const { stored, me } = ringOfTwo();
    expect(foldStored(stored).members.map(m => m.publicKey)).toEqual([me]);
  });
});
