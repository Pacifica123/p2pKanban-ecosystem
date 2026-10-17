import AsyncStorage from '@react-native-async-storage/async-storage';

import { summarizeProjectBoard } from './model';
import { PROJECT_BOARD_CACHE_KEY, buildRaw, loadLocalProjectBoard, loadProjectBoard } from './store';

jest.mock('@react-native-async-storage/async-storage', () => {
  const store = new Map<string, string>();
  return {
    __esModule: true,
    default: {
      getItem: jest.fn(async (key: string) => store.get(key) ?? null),
      setItem: jest.fn(async (key: string, value: string) => { store.set(key, value); }),
      removeItem: jest.fn(async (key: string) => { store.delete(key); }),
    },
  };
});

const NODE = 'http://192.168.0.101:8082';
const own = () => summarizeProjectBoard(buildRaw());
const newer = (by: number) => buildRaw().replace(
  `"boardRevision": ${own().revision}`,
  `"boardRevision": ${own().revision + by}`,
);

describe('project board on the phone', () => {
  beforeEach(async () => { await AsyncStorage.removeItem(PROJECT_BOARD_CACHE_KEY); });

  it('shows the APK copy without a node', async () => {
    const loaded = await loadLocalProjectBoard();
    expect(loaded.selection.chosen).toBe('build');
    expect(loaded.raw).toBe(buildRaw());
  });

  it('takes a newer board from the node and keeps it for mobile data', async () => {
    const fetchImpl = jest.fn(async () => new Response(newer(3), { status: 200 })) as unknown as typeof fetch;
    const online = await loadProjectBoard(NODE, fetchImpl);
    expect(online.selection.chosen).toBe('node');
    expect(online.selection.revision).toBe(own().revision + 3);
    expect((fetchImpl as jest.Mock).mock.calls[0][0]).toBe(`${NODE}/api/v1/project-board`);

    const offline = await loadProjectBoard(NODE, jest.fn(async () => { throw new TypeError('Network request failed'); }) as unknown as typeof fetch);
    expect(offline.selection.chosen).toBe('cache');
    expect(offline.selection.revision).toBe(own().revision + 3);
    expect(offline.node.state).toBe('unreachable');
  });

  it('asks with the saved etag and treats 304 as the same board', async () => {
    await AsyncStorage.setItem(PROJECT_BOARD_CACHE_KEY, newer(1));
    const fetchImpl = jest.fn(async () => new Response(null, { status: 304 })) as unknown as typeof fetch;
    const loaded = await loadProjectBoard(NODE, fetchImpl);
    const init = (fetchImpl as jest.Mock).mock.calls[0][1] as { headers: Record<string, string> };
    expect(init.headers['If-None-Match']).toBe(`"${summarizeProjectBoard(newer(1)).sha256}"`);
    expect(loaded.node).toEqual({ host: '192.168.0.101:8082', state: 'ok', sha256: summarizeProjectBoard(newer(1)).sha256 });
    expect(loaded.selection.revision).toBe(own().revision + 1);
  });

  it('an old node does not roll the board back and a foreign answer is dropped', async () => {
    const old = buildRaw().replace(`"boardRevision": ${own().revision}`, `"boardRevision": ${own().revision - 1}`);
    const loaded = await loadProjectBoard(NODE, jest.fn(async () => new Response(old, { status: 200 })) as unknown as typeof fetch);
    expect(loaded.selection.chosen).toBe('build');
    expect(loaded.selection.behind).toEqual([{ source: 'node', revision: own().revision - 1 }]);
    expect(await AsyncStorage.getItem(PROJECT_BOARD_CACHE_KEY)).toBeNull();

    const html = await loadProjectBoard(NODE, jest.fn(async () => new Response('<html>', { status: 200 })) as unknown as typeof fetch);
    expect(html.selection.rejected).toEqual([{ source: 'node', reason: 'not-json' }]);
    expect(html.selection.chosen).toBe('build');
  });
});
