import { describePause, describeSnapshot, stallGap, STALL_MS } from './stallWatch';
import { previousRunVerdict } from '../debug/blackBox';
jest.mock('@react-native-async-storage/async-storage', () => ({ setItem: jest.fn(async () => undefined), removeItem: jest.fn(async () => undefined), getItem: jest.fn(async () => null), multiGet: jest.fn(async () => []), multiSet: jest.fn(async () => undefined) }));
test('one late tick is not a stall, a held thread is', () => {
  expect(stallGap(0, 500)).toBe(0);
  expect(stallGap(0, 1_300)).toBeLessThan(STALL_MS);
  expect(stallGap(0, 30_500)).toBe(30_000);
});

const heap = { heapBytes: 0, gcCount: 0, gcMs: 0 };

test('the snapshot names requests in flight, oldest first, with short ids', () => {
  const text = describeSnapshot({
    heavy: ['Проверка реплик'],
    requests: [
      { method: 'GET', path: '/api/v1/boards/01a1478e-fb40-73b2-8ec8-1a5ad6ec9915/labels', ageMs: 3_000 },
      { method: 'POST', path: '/api/v1/auth/native/refresh', ageMs: 9_400 },
    ],
    screen: 'Board',
    heap: { heapBytes: 84 * 1024 * 1024, gcCount: 3, gcMs: 20 },
  });
  expect(text).toBe('шло: Проверка реплик; запросов к узлу в полёте 2: POST /auth/native/refresh 9.4 с, GET /boards/01a1478e/labels 3.0 с; экран Board; куча 84 МБ');
  expect(describeSnapshot({ heavy: [], requests: [], screen: null, heap })).toBe('запросов к узлу в полёте нет');
});

test('the pause says whether the collector or the timers held it', () => {
  expect(describePause({ from: 0, to: 14_000, linesInside: 0, before: { heapBytes: 1, gcCount: 4, gcMs: 100 }, after: { heapBytes: 1, gcCount: 6, gcMs: 12_600 } }))
    .toBe('сборка мусора за паузу: 2 раз, 12.5 с; JS за паузу ничего не записал');
  expect(describePause({ from: 0, to: 14_000, linesInside: 3, before: heap, after: heap }))
    .toContain('стояли таймеры, вероятно UI-поток');
});

test('the previous run is a freeze only when JS never saw the app leave', () => {
  expect(previousRunVerdict(null)).toBeNull();
  expect(previousRunVerdict({ at: '2026-10-20T10:05:00.000Z', appState: 'background', screen: 'Board', snapshot: '' })).toBeNull();
  expect(previousRunVerdict({ at: '2026-10-20T10:05:00.000Z', appState: 'active', screen: 'Board', snapshot: 'запросов к узлу в полёте 3' }))
    .toMatch(/последний пульс 2026-10-20T10:05:00.000Z, экран Board; запросов к узлу в полёте 3$/);
});
