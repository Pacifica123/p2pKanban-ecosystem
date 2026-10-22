import { ApiError, setApiNodeOrigin } from '../../shared/api/client';
import { nodeBlock, noteNodeSilent } from '../../shared/api/nodeReach';
import * as endpoints from '../../shared/api/endpoints';
import type { LocalBoardRuntime } from '../localFirst/useLocalBoard';
import * as catalog from '../roaming/catalog';
import {
  CROSS_ITEM_FOR_WEB, mobileSteps, newMobileContext, PROMPTS, type BoardDriver, type MobileAcceptanceContext, type NetworkState,
} from './mobileSteps';
import { buildAcceptanceReport, parseAcceptanceReport, renderAcceptanceMarkdown } from './report';
import { runSteps } from './runner';

jest.mock('@react-native-async-storage/async-storage', () => require('@react-native-async-storage/async-storage/jest/async-storage-mock'));
jest.mock('../../shared/api/endpoints');
jest.mock('../roaming/catalog', () => ({ refreshDeviceCatalog: jest.fn(), refreshWorkspaceCatalog: jest.fn() }));
jest.mock('../roaming/nostrRelay', () => ({
  fetchFromRelays: jest.fn(async () => ({ events: [{}], relayCount: 2, skipped: 0 })),
}));
jest.mock('../roaming/service', () => ({
  loadRoamingCapability: jest.fn(async () => ({ relays: ['wss://a', 'wss://b'], eventKind: 30078, boardTag: 't', minimumRelayAcks: 1 })),
}));
jest.mock('../deviceLink/service', () => ({ deviceFingerprint: jest.fn(async () => 'ab'.repeat(32)) }));

// Loose mocks: the fake node returns only the fields the plan reads.
const api = endpoints as unknown as Record<keyof typeof endpoints, jest.Mock>;
const cat = catalog as unknown as Record<keyof typeof catalog, jest.Mock>;

/** A node in memory plus a local board runtime that delivers its queue when the phone is online. */
function world() {
  let seq = 0;
  const id = () => `id-${++seq}`;
  const net: NetworkState = { isOnline: true, type: 'wifi' };
  const boards: any[] = [];
  const columns: any[] = [];
  const cards: any[] = [];
  const checklists: any[] = [];
  const at = () => new Date(Date.UTC(2026, 9, 17, 3, 0, seq)).toISOString();
  const http404 = () => new ApiError('Не найдено', { status: 404, http: { method: 'GET', path: '/api/v1/boards/x', body: null, errorId: null } });
  const offline = () => new ApiError('Не удалось связаться с узлом', { status: 0, code: 'NETWORK_ERROR' });
  const online = <T,>(value: () => T) => async () => { if (!net.isOnline || net.type !== 'wifi') throw offline(); return value(); };

  api.getBackendVersion.mockImplementation(online(() => ({ status: 'ok', version: '2.1.0' }) as any));
  api.getSession.mockImplementation(online(() => ({ authenticated: true }) as any));
  api.nativeSignIn.mockImplementation(async () => {
    throw new ApiError('Неверная почта или пароль', { status: 401, http: { method: 'POST', path: '/api/v1/auth/native/sign-in', body: '{}', errorId: null } });
  });
  api.getWorkspaces.mockImplementation(online(() => ({ items: [], pageInfo: {} }) as any));
  api.createWorkspace.mockImplementation(async (input) => ({ id: 'ws', ...input, isArchived: false }) as any);
  api.getBoards.mockImplementation(async (ws) => ({ items: boards.filter((b) => b.workspaceId === ws && !b.deleted) }) as any);
  api.createBoard.mockImplementation(async (ws, input) => { const b = { id: id(), workspaceId: ws, ...input, isArchived: false }; boards.push(b); return b; });
  api.deleteBoard.mockImplementation(async (boardId) => { const b = boards.find((x) => x.id === boardId); if (!net.isOnline) throw offline(); b.deleted = true; return b; });
  api.getBoard.mockImplementation(async () => { throw http404(); });
  api.getColumns.mockImplementation(async (boardId) => ({ items: columns.filter((c) => c.boardId === boardId) }) as any);
  api.createColumn.mockImplementation(async (boardId, input) => { const c = { id: id(), boardId, ...input }; columns.push(c); return c; });
  api.getCards.mockImplementation(async (boardId) => {
    if (!net.isOnline || net.type !== 'wifi') throw offline();
    return { items: cards.filter((c) => c.boardId === boardId && !c.deleted) } as any;
  });
  api.createCard.mockImplementation(async (boardId, input) => { const c = { id: id(), boardId, ...input, isArchived: false, createdAt: at() }; cards.push(c); return c; });
  api.deleteCard.mockImplementation(async (cardId) => { cards.find((c) => c.id === cardId).deleted = true; return {} as any; });
  api.getChecklists.mockImplementation(async (cardId) => ({ items: checklists.filter((l) => l.cardId === cardId) }) as any);
  api.createChecklist.mockImplementation(async (cardId, input) => { const l = { id: id(), cardId, ...input, items: [] }; checklists.push(l); return l; });
  api.createChecklistItem.mockImplementation(async (listId, input) => {
    const item = { id: id(), checklistId: listId, ...input, isDone: false }; checklists.find((l) => l.id === listId).items.push(item); return item;
  });
  api.updateChecklistItem.mockImplementation(async (itemId, input) => {
    const item = checklists.flatMap((l) => l.items).find((x) => x.id === itemId); Object.assign(item, input); return item;
  });
  cat.refreshWorkspaceCatalog.mockImplementation(async () => [{ id: 'ws', name: 'Приёмка p2pKanban' }] as any);
  cat.refreshDeviceCatalog.mockImplementation(async (ws) => boards.filter((b) => b.workspaceId === ws) as any);

  // The local-first board: operations wait in a queue and reach the node only while online.
  let queue: Array<() => void> = [];
  let local: any = null;
  const deliver = () => { if (net.isOnline) { queue.forEach((apply) => apply()); queue = []; } };
  const runtime = (): LocalBoardRuntime => ({
    snapshot: local, hydrated: true, syncMode: 'roaming', relayCount: 2, pendingCount: queue.length, relayPendingCount: 0,
    failedCount: 0, lastError: null,
    refresh: async () => deliver(),
    createCard: async (input: any) => {
      const card = { id: id(), boardId: local.board.id, ...input, isArchived: false, createdAt: at(), priority: null };
      local.cards.push(card);
      queue.push(() => cards.push({ ...card }));
      return card;
    },
    updateCard: async (cardId: string, input: any) => {
      Object.assign(local.cards.find((c: any) => c.id === cardId), input);
      queue.push(() => Object.assign(cards.find((c) => c.id === cardId), input));
    },
    createChecklist: async (cardId: string, title: string) => {
      const list = { id: id(), cardId, title, items: [] as any[] };
      local.checklistsByCardId[cardId] = [list];
      queue.push(() => checklists.push({ ...list, items: list.items }));
    },
    getCardChecklists: (cardId: string) => local.checklistsByCardId[cardId] || [],
    createChecklistItem: async (cardId: string, listId: string, title: string) => {
      local.checklistsByCardId[cardId][0].items.push({ id: id(), checklistId: listId, title, isDone: false });
    },
    toggleChecklistItem: async (cardId: string, _listId: string, itemId: string, isDone: boolean) => {
      local.checklistsByCardId[cardId][0].items.find((i: any) => i.id === itemId).isDone = isDone;
    },
    moveCard: async (cardId: string, columnId: string) => { queue.push(() => { cards.find((c) => c.id === cardId).columnId = columnId; }); },
    archiveCard: async (cardId: string) => { queue.push(() => { cards.find((c) => c.id === cardId).isArchived = true; }); },
    unarchiveCard: async (cardId: string) => { queue.push(() => { cards.find((c) => c.id === cardId).isArchived = false; }); },
    deleteCard: async (cardId: string) => {
      local.cards = local.cards.filter((c: any) => c.id !== cardId);
      queue.push(() => { cards.find((c) => c.id === cardId).deleted = true; });
    },
  }) as unknown as LocalBoardRuntime;
  const board: BoardDriver = {
    open: async (boardId) => {
      local = { board: boards.find((b) => b.id === boardId), cards: [], checklistsByCardId: {} };
      return runtime();
    },
    current: () => (local ? runtime() : null),
    close: () => { local = null; },
  };
  return { net, boards, cards, board };
}

function context(w: ReturnType<typeof world>, answers: Record<string, NetworkState | null>) {
  let theme: any = 'graphite';
  const palette: Record<string, string> = {};
  for (const t of require('../../app/uiThemes').UI_THEMES) palette[t.id] = t.colors.background;
  return newMobileContext({
    nodeOrigin: 'http://192.168.0.101:8082',
    user: { id: 'u1', email: 'john@example.test' },
    network: () => ({ ...w.net }),
    ask: async (prompt) => {
      const next = answers[prompt.id];
      if (!next) return false;
      Object.assign(w.net, next);
      return prompt.ready(w.net);
    },
    board: w.board,
    ui: { theme: () => theme, setTheme: (id) => { theme = id; }, background: () => palette[theme]! },
    sleep: async () => undefined,
  } as Omit<MobileAcceptanceContext, 'runId' | 'stamp' | 'node' | 'phaseCards'>, new Date('2026-10-17T03:00:00Z'));
}

describe('Android plan', () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => {
    setApiNodeOrigin('http://192.168.0.101:8082');
    // The poll burst goes through apiRequest itself.
    globalThis.fetch = jest.fn(async () => ({ ok: true, status: 200, headers: new Headers(), text: async () => '{"data":[]}' }) as unknown as Response);
  });
  afterEach(() => { globalThis.fetch = realFetch; });

  it('walks Wi-Fi → mobile network → no network → Wi-Fi and finds every card on the node', async () => {
    const w = world();
    const results = await runSteps(mobileSteps(), context(w, {
      [PROMPTS.cellular.id]: { isOnline: true, type: 'cellular' },
      [PROMPTS.offline.id]: { isOnline: false, type: 'none' },
      [PROMPTS.wifi.id]: { isOnline: true, type: 'wifi' },
    }));
    const failed = results.filter((r) => r.status === 'FAIL').map((r) => `${r.id}: ${r.detail}`);
    expect(failed).toEqual([]);
    const status = Object.fromEntries(results.map((r) => [r.id, r.status]));
    expect(status).toMatchObject({
      'auth.other-node': 'PASS', 'crud.local': 'PASS', 'crud.node': 'PASS', 'net.catalog-new-board': 'PASS',
      'net.cellular-card': 'PASS', 'offline.card': 'PASS', 'back.queue': 'PASS', 'back.node': 'PASS', cleanup: 'PASS',
      'cross.client': 'INFO',
    });
    expect(w.cards.map((c) => c.title)).toEqual(expect.arrayContaining([expect.stringMatching(/^Из мобильной сети/), expect.stringMatching(/^Без сети/)]));
    expect(w.boards.filter((b) => !b.deleted).map((b) => b.name)).toEqual(['Встречная доска']);
    const androidCard = w.cards.find((c) => c.title.startsWith('android ·'));
    expect(androidCard).toBeTruthy();
    expect(results.at(-1)!.id).toBe('cleanup');

    const report = buildAcceptanceReport({ runId: 'r', startedAt: '2026-10-17T03:00:00.000Z', finishedAt: '2026-10-17T03:10:00.000Z',
      software: { direction: 'mobile', version: '2.1.0', build: '28', commit: null }, platform: 'Android 12', node: null, steps: results, remaining: [] });
    const text = renderAcceptanceMarkdown(report);
    expect(text).not.toContain('john@example.test');
    expect(parseAcceptanceReport(text).summary.verdict).toBe('PASS');
    expect(CROSS_ITEM_FOR_WEB).toBe('Отметит web');
  });

  it('asks the node afresh even while an earlier silence still pauses requests (run jd21drv3)', async () => {
    const w = world();
    noteNodeSilent();
    expect(nodeBlock('http://192.168.0.101:8082')?.reason).toBe('silent');
    let blockedWhenAsked: unknown = 'not asked';
    api.getBackendVersion.mockImplementation(async () => {
      blockedWhenAsked = nodeBlock('http://192.168.0.101:8082');
      return { status: 'ok', version: '2.1.0' } as any;
    });
    const results = await runSteps(mobileSteps().filter((step) => step.id.startsWith('env.')), context(w, {}));
    expect(blockedWhenAsked).toBeNull();
    expect(results.find((r) => r.id === 'env.node')!.status).not.toBe('FAIL');
  });

  it('names the bug when a board created on the node does not reach the mobile network', async () => {
    const w = world();
    cat.refreshDeviceCatalog.mockImplementation(async () => [] as any);
    const results = await runSteps(mobileSteps(), context(w, { [PROMPTS.cellular.id]: { isOnline: true, type: 'cellular' } }));
    const step = results.find((r) => r.id === 'net.catalog-new-board')!;
    expect(step.status).toBe('FAIL');
    expect(step.detail).toContain('только доски, открытые в Wi-Fi');
    // Skipped phases skip their steps instead of failing them.
    expect(results.find((r) => r.id === 'offline.card')!.status).toBe('SKIP');
    expect(results.find((r) => r.id === 'back.node')!.status).toBe('SKIP');
    // The fake node still answers on the mobile network; a real LAN node would make this a WARN, not a crash.
    expect(results.find((r) => r.id === 'cleanup')!.status).toBe('PASS');
  });
});
