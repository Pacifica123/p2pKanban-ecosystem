import {
  COOL_DOWN_MS,
  MAX_COOL_DOWN_MS,
  nodeBlock,
  noteNodeAnswered,
  noteNodeSilent,
  resetNodeReach,
  setApiNetworkType,
} from './nodeReach';

const lan = 'http://192.168.0.101:8082';
const pub = 'https://kanban.example.org';

beforeEach(() => { setApiNetworkType('wifi'); resetNodeReach(); });

test('a LAN node is not asked from mobile data, a VPN or Wi-Fi may reach it', () => {
  setApiNetworkType('cellular');
  expect(nodeBlock(lan)?.reason).toBe('lan-from-cellular');
  expect(nodeBlock(pub)).toBeNull();
  setApiNetworkType('vpn');
  expect(nodeBlock(lan)).toBeNull();
  setApiNetworkType('wifi');
  expect(nodeBlock(lan)).toBeNull();
});

test('a silent node is skipped for a cool-down that grows, and one answer ends it', () => {
  expect(noteNodeSilent(0)).toBe(COOL_DOWN_MS);
  expect(nodeBlock(lan, 1_000)?.reason).toBe('silent');
  expect(nodeBlock(lan, COOL_DOWN_MS)).toBeNull();
  expect(noteNodeSilent(COOL_DOWN_MS + 12_000)).toBe(COOL_DOWN_MS * 2);
  for (let index = 0; index < 5; index += 1) noteNodeSilent(10_000_000 * (index + 1));
  expect(nodeBlock(lan, 50_000_000 + MAX_COOL_DOWN_MS - 1)?.retryInMs).toBe(1);
  expect(noteNodeAnswered()).toBe(true);
  expect(nodeBlock(lan, 50_000_000 + 1)).toBeNull();
  expect(noteNodeAnswered()).toBe(false);
});

test('requests that fail together count as one silence', () => {
  expect(noteNodeSilent(0)).toBe(COOL_DOWN_MS);
  expect(noteNodeSilent(5)).toBe(0);
  expect(noteNodeSilent(10)).toBe(0);
  expect(noteNodeSilent(COOL_DOWN_MS + 1)).toBe(COOL_DOWN_MS * 2);
});

test('a new network forgets the silence', () => {
  noteNodeSilent(Date.now());
  expect(nodeBlock(lan)).not.toBeNull();
  expect(setApiNetworkType('cellular')).toBe(true);
  expect(nodeBlock(pub)).toBeNull();
  expect(setApiNetworkType('cellular')).toBe(false);
});
