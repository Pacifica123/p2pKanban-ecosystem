import { finalizeEvent, getPublicKey } from 'nostr-tools/pure';
import {
  LINK_PROTOCOL,
  GRANT_KIND,
  RESPONSE_KIND,
  verifyChain,
  verifyReplicationChain,
  extendChain,
  encryptPack,
  decryptPack,
  checkRequest,
  REQUEST_KIND,
} from './protocol';
const a = new Uint8Array(32).fill(1),
  b = new Uint8Array(32).fill(2),
  c = new Uint8Array(32).fill(3),
  now = () => Math.floor(Date.now() / 1000);
const grant = (extra = {}) =>
  finalizeEvent(
    {
      kind: GRANT_KIND,
      created_at: now(),
      tags: [],
      content: JSON.stringify({
        protocol: LINK_PROTOCOL,
        workspaceId: 'w',
        boardId: 'b',
        userId: 'u',
        epoch: 2,
        subject: getPublicKey(b),
        canDelegate: true,
        parentId: null,
        expiresAt: now() + 600,
        ...extra,
      }),
    },
    a,
  );
test('delegation cannot change scope, device, expiry or permission', () => {
  const root = grant(),
    chain = extendChain(b, [root], getPublicKey(c));
  expect(verifyChain(chain, getPublicKey(c)).root).toBe(getPublicKey(a));
  expect(() => verifyChain(chain, getPublicKey(b))).toThrow();
  for (const extra of [{ boardId: 'other' }, { expiresAt: now() + 9999 }]) {
    const changed = finalizeEvent(
      {
        ...chain[1]!,
        content: JSON.stringify({ ...JSON.parse(chain[1]!.content), ...extra }),
      },
      b,
    );
    expect(() => verifyChain([root, changed], getPublicKey(c))).toThrow();
  }
  expect(() =>
    extendChain(b, [grant({ canDelegate: false })], getPublicKey(c)),
  ).toThrow();
  expect(() =>
    verifyChain([grant({ expiresAt: now() - 1 })], getPublicKey(b)),
  ).toThrow();
});
test('multi-chunk Unicode encryption rejects wrong keys and tampering', () => {
  const data = { text: 'Текст 🐈\n'.repeat(8000) },
    parts = encryptPack(a, getPublicKey(b), data),
    reply = finalizeEvent(
      {
        kind: RESPONSE_KIND,
        created_at: now(),
        tags: [],
        content: JSON.stringify({
          protocol: LINK_PROTOCOL,
          recipient: getPublicKey(b),
          parts,
        }),
      },
      a,
    );
  expect(parts.length).toBeGreaterThan(1);
  expect(decryptPack(b, reply)).toEqual(data);
  expect(() => decryptPack(c, reply)).toThrow();
  reply.content += ' ';
  expect(() => decryptPack(b, reply)).toThrow();
});
test('challenge expiry is bounded', () => {
  for (const seconds of [-1, 1000])
    expect(() =>
      checkRequest(
        finalizeEvent(
          {
            kind: REQUEST_KIND,
            created_at: now(),
            tags: [],
            content: JSON.stringify({
              protocol: LINK_PROTOCOL,
              expiresAt: now() + seconds,
            }),
          },
          a,
        ),
      ),
    ).toThrow();
});

test('enrolled membership survives invitation expiry, while new delegation remains bounded', () => {
  const chain = extendChain(b, [grant()], getPublicKey(c));
  expect(() => verifyChain(chain,getPublicKey(c),now()+1000)).toThrow();
  expect(verifyReplicationChain(chain,getPublicKey(c),now()+1000).root).toBe(getPublicKey(a));
  expect(() => verifyReplicationChain(chain,getPublicKey(c),0)).toThrow();
});
