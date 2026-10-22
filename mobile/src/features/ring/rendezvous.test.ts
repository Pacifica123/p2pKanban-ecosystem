/** rendezvous/1 on mobile against contracts/rendezvous/1/vectors. */
import { bytesToHex, hexToBytes } from '@noble/hashes/utils.js';
import { getPublicKey } from 'nostr-tools/pure';

import { b64url, unb64url } from './protocol';
import {
  confirmCode, mailboxEvents, newQr, NewerQrError, openMailbox, qrDecode, qrEncode, refuseMessage, sessionId, sessionKey,
  sponsorReview, verifyWelcome,
} from './rendezvous';

declare const __dirname: string;
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { readFileSync } = require('fs') as { readFileSync: (path: string, encoding: 'utf8') => string };
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { join } = require('path') as { join: (...parts: string[]) => string };

const CONTRACTS = join(__dirname, '../../../../contracts');
const load = (name: string) => JSON.parse(readFileSync(join(CONTRACTS, 'rendezvous/1/vectors', name), 'utf8'));
const vectors = ['invite-mode.json', 'join-mode.json', 'refuse-ring-merge.json'].map(name => [name, load(name)] as const);
const random = (n: number) => crypto.getRandomValues(new Uint8Array(n));
const adminState = (sponsor: string) => ({ accountId: '00'.repeat(32), removed: [],
  members: [{ publicKey: sponsor, name: 'Телефон', kind: 'android' as const, role: 'admin' as const, addedBy: null, addEntry: 'x' }] });

describe.each(vectors)('rendezvous/1 %s', (name, data) => {
  const secret = unb64url(data.qr.s);
  const mails = () => openMailbox(data.events, secret);

  it('QR text and derived values match', () => {
    expect(qrEncode(data.qr)).toBe(data.qrText);
    expect(qrDecode(data.qrText)).toEqual(data.qr);
    const session = sessionId(secret);
    expect(session).toBe(data.derived.sessionId);
    expect(bytesToHex(sessionKey(secret))).toBe(data.derived.sessionKey);
    expect(confirmCode(session, data.roles.joiner)).toBe(data.derived.confirmCode);
  });

  it('mailbox opens to the expected messages in any order, and only with the secret', () => {
    expect(mails().map(m => m.message)).toEqual(data.expectedMessages);
    expect(openMailbox([...data.events].reverse(), secret)).toEqual(mails());
    expect(openMailbox(data.events, new Uint8Array(32))).toEqual([]);
  });

  it('sponsor and joiner reach the vector outcome', () => {
    const sponsor = data.roles.sponsor;
    const before = data.qr.x - 60;
    const review = sponsorReview(data.qr, mails(), sponsor, adminState(sponsor), true, before);
    const refuse = data.expectedMessages.find((m: any) => m.type === 'refuse');
    if (refuse) {
      expect('refusal' in review && refuseMessage(data.derived.sessionId, review.refusal)).toEqual(refuse);
    } else {
      expect('hello' in review && review.hello).toEqual(data.expectedMessages[0]);
      const welcome = mails().find(m => m.message.type === 'welcome')!;
      const checked = verifyWelcome(welcome, data.qr, data.roles.joiner);
      expect('state' in checked && checked.state).toEqual(data.expectedRingAfter);
      expect(verifyWelcome(welcome, data.qr, '11'.repeat(32))).toMatchObject({ refusal: { reason: 'welcome-invalid' } });
    }
    expect(sponsorReview(data.qr, mails(), sponsor, adminState(sponsor), true, data.qr.x + 1)).toMatchObject({ refusal: { reason: 'expired' } });
    expect(sponsorReview(data.qr, mails(), sponsor, adminState(sponsor), false, before)).toMatchObject({ refusal: { reason: 'sponsor-stale' } });
  });
});

describe('rendezvous/1 made here', () => {
  it('a second hello contests an invite', () => {
    const data = load('invite-mode.json');
    const secret = unb64url(data.qr.s);
    const intruder = hexToBytes('00'.repeat(31) + '09');
    const hello = { ...data.expectedMessages[0], device: { ...data.expectedMessages[0].device, publicKey: getPublicKey(intruder) } };
    const events = [...data.events, ...mailboxEvents(intruder, secret, hello, 1791244831, data.qr.x, random)];
    const review = sponsorReview(data.qr, openMailbox(events, secret), data.roles.sponsor, adminState(data.roles.sponsor), true, data.qr.x - 60);
    expect(review).toMatchObject({ refusal: { reason: 'contested' } });
  });

  it('a large welcome travels in 48 KiB parts', () => {
    const sponsor = hexToBytes('00'.repeat(31) + '01');
    const secret = random(32);
    const message = { type: 'welcome', sessionId: sessionId(secret), padding: 'я'.repeat(70000) };
    const events = mailboxEvents(sponsor, secret, message, 1791244900, 1791245400, random);
    expect(events).toHaveLength(3);
    expect(openMailbox([...events].reverse(), secret).map(m => m.message)).toEqual([message]);
    expect(openMailbox(events.slice(0, 2), secret)).toEqual([]);
  });

  it('a new QR roundtrips, lives at most ten minutes, and a newer version is named', () => {
    const { qr, secret } = newQr('join', getPublicKey(hexToBytes('00'.repeat(31) + '02')), 'Телефон', 'android',
      ['wss://a.example', 'ws://plain.example'], 1000, random, 3600);
    expect(qr.x).toBe(1600);
    expect(qr.r).toEqual(['wss://a.example']);
    expect(qrDecode(qrEncode(qr))).toEqual(qr);
    expect(qr.s).toBe(b64url(secret));
    expect(() => qrDecode('p2pkanban:rv2:abc')).toThrow(NewerQrError);
    expect(() => qrDecode('https://example.com')).toThrow('Это не QR встречи');
  });
});
