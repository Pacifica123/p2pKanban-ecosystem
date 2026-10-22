// Relay deadlines in mobile data (2026-10-22, er-01235c9feb389f7a): opening the
// socket, silence between frames and the whole exchange are separate budgets.
import {finalizeEvent} from 'nostr-tools/pure';
import {
  fetchFromRelays,
  RELAY_OPEN_TIMEOUT_MS,
  RELAY_QUIET_TIMEOUT_MS,
  RELAY_TOTAL_TIMEOUT_MS,
} from './nostrRelay';

const key = new Uint8Array(32).fill(1);
const event = (n: number) => finalizeEvent({kind: 1979, created_at: n, tags: [['d', 'board']], content: `e${n}`}, key);
let sockets: FakeSocket[] = [];
class FakeSocket {
  onopen?: () => void;
  onmessage?: (message: {data: string}) => void;
  onerror?: () => void;
  onclose?: () => void;
  sent: any[][] = [];
  constructor(public url: string) { sockets.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  close() { this.onclose?.(); }
  receive(frame: any[]) { this.onmessage?.({data: JSON.stringify(frame)}); }
  get subscription() { return this.sent.find(frame => frame[0] === 'REQ')?.[1]; }
}
beforeEach(() => {
  jest.useFakeTimers();
  sockets = [];
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket;
});
afterEach(() => jest.useRealTimers());
const read = () => fetchFromRelays({relays: ['wss://slow'], kind: 1979, boardTag: 'board'});

test('a slow handshake does not eat the time for the answer', async () => {
  const result = read();
  jest.advanceTimersByTime(RELAY_OPEN_TIMEOUT_MS - 1_000);
  sockets[0]!.onopen?.();
  jest.advanceTimersByTime(RELAY_QUIET_TIMEOUT_MS - 1_000);
  sockets[0]!.receive(['EVENT', sockets[0]!.subscription, event(1)]);
  sockets[0]!.receive(['EOSE', sockets[0]!.subscription]);
  await expect(result).resolves.toMatchObject({relayCount: 1});
});

test('a relay that keeps streaming a long history is not silent', async () => {
  const result = read();
  sockets[0]!.onopen?.();
  for (let n = 1; n <= 4; n += 1) {
    jest.advanceTimersByTime(RELAY_QUIET_TIMEOUT_MS - 1_000);
    sockets[0]!.receive(['EVENT', sockets[0]!.subscription, event(n)]);
  }
  sockets[0]!.receive(['EOSE', sockets[0]!.subscription]);
  const {events} = await result;
  expect(events).toHaveLength(4);
});

test('silence after the socket opened still fails after the quiet budget', async () => {
  const result = read();
  sockets[0]!.onopen?.();
  jest.advanceTimersByTime(RELAY_QUIET_TIMEOUT_MS);
  await expect(result).rejects.toThrow('открыл соединение, но не ответил за 8 с');
});

test('a socket that never opens is reported as the network', async () => {
  const result = read();
  jest.advanceTimersByTime(RELAY_OPEN_TIMEOUT_MS);
  await expect(result).rejects.toThrow('не открыл соединение за 10 с');
});

test('the whole exchange has a ceiling even while frames keep coming', async () => {
  const result = read();
  sockets[0]!.onopen?.();
  for (let n = 1; n * 5_000 < RELAY_TOTAL_TIMEOUT_MS + 5_000; n += 1) {
    jest.advanceTimersByTime(5_000);
    sockets[0]!.receive(['EVENT', sockets[0]!.subscription, event(n)]);
  }
  await expect(result).rejects.toThrow('не закончил за 30 с');
});
