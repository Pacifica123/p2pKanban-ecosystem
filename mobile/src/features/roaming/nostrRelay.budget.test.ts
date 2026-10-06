import {finalizeEvent, type Event} from 'nostr-tools/pure';

const mockVerify = jest.fn();
jest.mock('nostr-tools/pure', () => {
  const actual = jest.requireActual('nostr-tools/pure');
  return {...actual, verifyEvent: (event: Event) => { mockVerify(event.id); return actual.verifyEvent(event); }};
});
import {fetchFromRelays} from './nostrRelay';

const key = new Uint8Array(32).fill(1);
const event = (n: number) => finalizeEvent({kind:1979,created_at:1000+n,tags:[['d','board']],content:`c${n}`},key);
let served: Record<string, Event[]> = {};
let lastFilter: any;
class FakeSocket {
  onopen?: () => void;
  onmessage?: (message:{data:string}) => void;
  onerror?: () => void;
  onclose?: () => void;
  constructor(public url:string) { queueMicrotask(() => this.onopen?.()); }
  send(raw:string) {
    const frame = JSON.parse(raw);
    if (frame[0] !== 'REQ') return;
    lastFilter = frame[2];
    for (const item of served[this.url] || []) this.onmessage?.({data:JSON.stringify(['EVENT',frame[1],item])});
    this.onmessage?.({data:JSON.stringify(['EOSE',frame[1]])});
  }
  close() { this.onclose?.(); }
}
beforeEach(() => {
  served = {};
  mockVerify.mockClear();
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket;
});

test('history already in the journal is not verified again on every poll', async () => {
  const history = Array.from({length: 20}, (_, n) => event(n));
  const fresh = event(99);
  served = {r1: [...history, fresh], r2: [...history, fresh]};
  const result = await fetchFromRelays({relays:['r1','r2'],kind:1979,boardTag:'board',
    knownIds:new Set(history.map(item => item.id))});
  expect(result.events.map(item => item.id)).toEqual([fresh.id]);
  expect(result.skipped).toBe(40);
  // One check per distinct new event, not one per relay copy.
  expect(mockVerify).toHaveBeenCalledTimes(1);
});

test('a forged copy under a real id does not hide the genuine copy from another relay', async () => {
  const genuine = event(1);
  const forged = {...genuine, content: 'forged'};
  served = {r1: [forged], r2: [genuine]};
  const result = await fetchFromRelays({relays:['r1','r2'],kind:1979,boardTag:'board'});
  expect(result.events).toHaveLength(1);
  expect(result.events[0]!.content).toBe('c1');
});

test('incremental pull asks relays only for events after the cursor', async () => {
  served = {r1: []};
  await fetchFromRelays({relays:['r1'],kind:1979,boardTag:'board',since:1234});
  expect(lastFilter.since).toBe(1234);
  await fetchFromRelays({relays:['r1'],kind:1979,boardTag:'board'});
  expect(lastFilter.since).toBeUndefined();
});

test('a closed screen stops verification instead of finishing the backlog', async () => {
  served = {r1: Array.from({length: 5}, (_, n) => event(n))};
  const controller = new AbortController();
  controller.abort();
  await expect(fetchFromRelays({relays:['r1'],kind:1979,boardTag:'board',signal:controller.signal}))
    .rejects.toThrow('Синхронизация остановлена');
  expect(mockVerify).not.toHaveBeenCalled();
});
