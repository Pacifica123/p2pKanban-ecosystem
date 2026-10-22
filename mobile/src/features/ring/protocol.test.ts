/**
 * The mobile implementation of the ring contracts checked against the shared
 * vectors in contracts/ (account-ring/1, keyring/1). The vectors are the
 * source of truth; when this test and contract_ref.py disagree, this side is wrong.
 */
import { hexToBytes } from '@noble/hashes/utils.js';
import { getPublicKey } from 'nostr-tools/pure';

import {
  accountTag, foldRing, keyringDigest, makeEntry, mergeKeyrings, openSealedEvent, presenceSkew, sealedEvent, b64url,
} from './protocol';

declare const __dirname: string;
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { readdirSync, readFileSync } = require('fs') as { readdirSync: (path: string) => string[]; readFileSync: (path: string, encoding: 'utf8') => string };
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { join } = require('path') as { join: (...parts: string[]) => string };

const CONTRACTS = join(__dirname, '../../../../contracts');
const vector = (path: string) => JSON.parse(readFileSync(join(CONTRACTS, path), 'utf8'));
const random = (n: number) => crypto.getRandomValues(new Uint8Array(n));

describe('account-ring/1 vectors', () => {
  const dir = join(CONTRACTS, 'account-ring/1/vectors');
  const ringVectors = readdirSync(dir).filter(name => name.startsWith('ring-'));

  it('has every ring vector', () => expect(ringVectors.length).toBeGreaterThanOrEqual(7));

  it.each(ringVectors)('%s folds to the expected state in any order', (name: string) => {
    const data = JSON.parse(readFileSync(join(dir, name), 'utf8'));
    expect(foldRing(data.entries, data.accountId)).toEqual(data.expected);
    expect(foldRing([...data.entries].reverse(), data.accountId)).toEqual(data.expected);
  });

  it('keys derive their public keys', () => {
    for (const key of vector('account-ring/1/vectors/keys.json').keys) {
      expect(getPublicKey(hexToBytes(key.secretKey))).toBe(key.publicKey);
    }
  });

  it('sealed ring log opens for the recipient only', () => {
    const data = vector('account-ring/1/vectors/sealed-ring-log.json');
    const account = data.expectedPlaintext.accountId;
    expect(accountTag(account)).toBe(data.accountTag);
    const opened = openSealedEvent(hexToBytes(data.recipient.secretKey), data.event, account);
    expect(opened.type).toBe('ring-log');
    expect(opened.plain).toEqual(data.expectedPlaintext);
    expect(() => openSealedEvent(hexToBytes(data.outsider.secretKey), data.event, account)).toThrow();
    const tampered = { ...data.event, content: data.event.content.replace('"ciphertext":"', '"ciphertext":"A') };
    expect(() => openSealedEvent(hexToBytes(data.recipient.secretKey), tampered, account)).toThrow();
  });

  it('presence opens and skew matches', () => {
    const data = vector('account-ring/1/vectors/presence.json');
    const me = hexToBytes(data.recipient.secretKey);
    const presences = data.events.map((event: any, i: number) => {
      const opened = openSealedEvent(me, event, data.expectedPlaintexts[i].accountId);
      expect(opened.plain).toEqual(data.expectedPlaintexts[i]);
      return opened.plain;
    });
    expect(presenceSkew(presences, data.ringHeads)).toEqual(data.expectedSkew);
  });

  it('entries made here fold, and sealed copies made here open on the other side', () => {
    const node = hexToBytes('00'.repeat(31) + '01');
    const phone = hexToBytes('00'.repeat(31) + '02');
    const genesis = makeEntry(node, { type: 'genesis', parents: [], nonce: b64url(new Uint8Array(16).fill(7)),
      device: { publicKey: getPublicKey(node), name: 'Узел', kind: 'web', role: 'admin' },
      relays: { urls: ['wss://relay-a.example'], minAcks: 1 } }, 1791244860);
    const add = makeEntry(node, { type: 'add', accountId: genesis.id, parents: [genesis.id], via: 'rendezvous',
      device: { publicKey: getPublicKey(phone), name: 'Телефон в «поездке»', kind: 'android', role: 'admin' } }, 1791244920);
    const state = foldRing([add, genesis], genesis.id);
    expect(state.members.map(m => m.name)).toEqual(expect.arrayContaining(['Узел', 'Телефон в «поездке»']));
    expect(state.rejected).toEqual([]);
    const sealed = sealedEvent(phone, 'ring-log', genesis.id, [getPublicKey(node), getPublicKey(phone)],
      { protocol: 'p2p-kanban-account-ring/1', accountId: genesis.id, entries: [genesis, add] }, 1791245000, random);
    expect(openSealedEvent(node, sealed, genesis.id).plain.entries).toEqual([genesis, add]);
  });
});

describe('keyring/1 vectors', () => {
  it('sealed keyring opens and merge matches', () => {
    const data = vector('keyring/1/vectors/sealed-keyring.json');
    const opened = openSealedEvent(hexToBytes(data.recipient.secretKey), data.event, data.expectedPlaintext.accountId);
    expect(opened.type).toBe('keyring');
    expect(opened.plain).toEqual(data.expectedPlaintext);
    const merge = vector('keyring/1/vectors/merge.json');
    const items = mergeKeyrings(merge.copies);
    expect(items).toEqual(merge.expected.items);
    expect(keyringDigest(items)).toBe(merge.expected.digest);
    expect(mergeKeyrings([...merge.copies].reverse())).toEqual(items);
  });
});
