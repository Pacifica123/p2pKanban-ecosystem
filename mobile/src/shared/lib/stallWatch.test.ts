import { stallGap, STALL_MS } from './stallWatch';
jest.mock('@react-native-async-storage/async-storage', () => ({ setItem: jest.fn(async () => undefined), removeItem: jest.fn(async () => undefined), getItem: jest.fn(async () => null) }));
test('one late tick is not a stall, a held thread is', () => {
  expect(stallGap(0, 1_000)).toBe(0);
  expect(stallGap(0, 1_300)).toBeLessThan(STALL_MS);
  expect(stallGap(0, 31_000)).toBe(30_000);
});
