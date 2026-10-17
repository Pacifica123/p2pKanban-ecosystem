import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import {
  ACCEPTANCE_REPORT, buildAcceptanceReport, parseAcceptanceReport, renderAcceptanceMarkdown, reportFileName, type StepResult,
} from '@/features/acceptance/report';
import { fail, info, pass, runSteps, type StepDefinition } from '@/features/acceptance/runner';
import {
  CROSS_BOARD, CROSS_ITEM_FOR_ANDROID, CROSS_ITEM_FOR_WEB, LONG_COMMENT, newWebContext, TEST_WORKSPACE, webSteps,
} from '@/features/acceptance/webSteps';
import { ApiError } from '@/shared/api/errors';

const software = { direction: 'web' as const, version: '2.1.0', build: 'abc', commit: '0123456789abcdef0123456789abcdef01234567' };

describe('runner', () => {
  it('turns throws into FAIL and skips steps whose prerequisite did not pass', async () => {
    const steps: StepDefinition<object>[] = [
      { id: 'a', phase: 'p', title: 'A', run: async () => 'ok' },
      { id: 'b', phase: 'p', title: 'B', run: async () => { throw new ApiError('нет доски', { status: 404, http: { method: 'GET', path: '/boards/x', body: null, errorId: null } }); } },
      { id: 'c', phase: 'p', title: 'C', needs: ['b'], run: async () => pass() },
      { id: 'd', phase: 'p', title: 'D', needs: ['a'], run: async () => info('справка') },
      { id: 'e', phase: 'p', title: 'E', needs: ['d'], run: async () => fail('плохо') },
    ];
    const results = await runSteps(steps, {});
    expect(results.map((r) => r.status)).toEqual(['PASS', 'FAIL', 'SKIP', 'INFO', 'FAIL']);
    expect(results[0]!.detail).toBe('ok');
    expect(results[1]!.detail).toContain('GET /boards/x → 404');
    expect(results[2]!.detail).toContain('«B»');
  });

  it('stops on abort', async () => {
    const controller = new AbortController();
    controller.abort();
    const results = await runSteps([{ id: 'a', phase: 'p', title: 'A', run: async () => pass() }], {}, { signal: controller.signal });
    expect(results[0]!.status).toBe('SKIP');
  });
});

describe('p2p-kanban-acceptance-report/1', () => {
  const steps: StepResult[] = [
    { id: 'x', phase: 'Сеанс', title: 'Шаг | с чертой', status: 'PASS', covers: ['auth-poll-limit'], detail: 'Authorization: Bearer abc.def.ghi', ms: 3 },
    { id: 'y', phase: 'Карточки', title: 'Шаг 2', status: 'FAIL', covers: [], detail: 'строка 1\nстрока 2', ms: 5 },
  ];
  const report = buildAcceptanceReport({ runId: 'r1', startedAt: '2026-10-17T03:00:00.000Z', finishedAt: '2026-10-17T03:01:00.000Z',
    software, platform: 'Firefox', node: { origin: 'http://192.168.0.105:8080', version: '2.1.0', build: 'f5d1', commit: null },
    steps, remaining: ['посмотреть глазами'] });

  it('counts statuses and redacts details', () => {
    expect(report.protocol).toBe(ACCEPTANCE_REPORT);
    expect(report.summary).toMatchObject({ PASS: 1, FAIL: 1, verdict: 'FAIL' });
    expect(report.steps[0]!.detail).not.toContain('abc.def.ghi');
  });

  it('renders Markdown for a person and JSON a machine reads back', () => {
    const text = renderAcceptanceMarkdown(report);
    expect(text).toMatch(/^# p2pKanban: проверка приёмки — web 2\.1\.0/);
    expect(text).toContain('**Итог: FAIL**');
    expect(text).toContain('Шаг \\| с чертой');
    expect(text).toContain('строка 1<br>строка 2');
    expect(text).toContain('## Осталось человеку (D)');
    expect(parseAcceptanceReport(text)).toEqual(report);
    expect(reportFileName(report)).toBe('p2pkanban-acceptance-web-20261017T030000Z.md');
  });
});

// A node in memory: just enough of /api/v1 for the web plan to run end to end.
function fakeNode() {
  let seq = 0;
  const id = () => `00000000-0000-4000-8000-${String(++seq).padStart(12, '0')}`;
  const at = () => new Date(Date.UTC(2026, 9, 17, 3, 0, seq)).toISOString();
  const workspaces: any[] = [];
  const boards: any[] = [];
  const columns: any[] = [];
  const cards: any[] = [];
  const checklists: any[] = [];
  const comments: any[] = [];
  const labels: any[] = [];
  const calls: string[] = [];
  const bundle = JSON.parse(readFileSync(join(__dirname, '../../../fixtures/board-backup-v1.json'), 'utf8'));

  const ok = (data: unknown, status = 200) => new Response(JSON.stringify({ data }), {
    status, headers: { 'Content-Type': 'application/json', 'x-p2p-kanban-node': `2.1.0; build=f5d187667317; commit=${software.commit}` },
  });
  const notFound = () => new Response(JSON.stringify({ error: { code: 'NOT_FOUND', message: 'Не найдено' } }), { status: 404 });
  const withItems = (card: any) => ({ ...card, items: undefined });

  const handler = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const method = (init.method ?? 'GET').toUpperCase();
    const body = init.body ? JSON.parse(String(init.body)) : {};
    if (!url.pathname.startsWith('/api/v1')) return new Response('{}', { status: 503 });
    const path = url.pathname.slice('/api/v1'.length);
    calls.push(`${method} ${path}`);
    const m = (re: RegExp) => path.match(re);
    let r: RegExpMatchArray | null;
    if (path === '/health') return ok({ status: 'ok', service: 'p2p', version: '2.1.0', env: 'test' });
    if (path === '/auth/session') return ok({ authenticated: true, mode: 'cookie', sessionId: 's', deviceId: 'd', user: null });
    if (path === '/auth/device-link/lan/inbox') return ok([]);
    if (path === '/auth/refresh') return ok({ authenticated: true, accessToken: 'next-token', user: {} });
    if (path === '/workspaces' && method === 'GET') return ok({ items: workspaces, pageInfo: {} });
    if (path === '/workspaces' && method === 'POST') { const w = { id: id(), ...body, isArchived: false }; workspaces.push(w); return ok(w, 201); }
    if ((r = m(/^\/workspaces\/([^/]+)\/boards$/))) {
      if (method === 'GET') return ok({ items: boards.filter((b) => b.workspaceId === r![1] && !b.deleted), pageInfo: {} });
      const b = { id: id(), workspaceId: r[1], ...body, isArchived: false, createdAt: at() }; boards.push(b); return ok(b, 201);
    }
    if ((r = m(/^\/boards\/([^/]+)$/))) {
      const b = boards.find((x) => x.id === r![1] && !x.deleted);
      if (!b) return notFound();
      if (method === 'DELETE') b.deleted = true;
      return ok(b);
    }
    if ((r = m(/^\/boards\/([^/]+)\/columns$/))) {
      if (method === 'GET') return ok({ items: columns.filter((c) => c.boardId === r![1]) });
      const c = { id: id(), boardId: r[1], ...body }; columns.push(c); return ok(c, 201);
    }
    if ((r = m(/^\/boards\/([^/]+)\/cards$/))) {
      if (method === 'GET') {
        const all = url.searchParams.get('localVisibility') === 'all';
        return ok({ items: cards.filter((c) => c.boardId === r![1] && !c.deleted && (all || !c.isArchived)), pageInfo: {} });
      }
      const c = { id: id(), boardId: r[1], ...body, priority: body.priority ?? null, isArchived: false, labelIds: [], createdAt: at(), position: seq };
      cards.push(c); return ok(c, 201);
    }
    if ((r = m(/^\/cards\/([^/]+)(\/[a-z-]+)?$/))) {
      const c = cards.find((x) => x.id === r![1] && !x.deleted);
      if (!c) return notFound();
      const action = r[2];
      if (!action && method === 'PATCH') Object.assign(c, body);
      if (!action && method === 'DELETE') c.deleted = true;
      if (action === '/move') c.columnId = body.targetColumnId;
      if (action === '/archive') c.isArchived = true;
      if (action === '/unarchive') c.isArchived = false;
      if (action === '/labels') c.labelIds = body.labelIds;
      if (action === '/checklists') {
        if (method === 'GET') return ok({ items: checklists.filter((l) => l.cardId === c.id) });
        const l = { id: id(), cardId: c.id, ...body, items: [] }; checklists.push(l); return ok(l, 201);
      }
      if (action === '/comments') {
        if (method === 'GET') return ok({ items: comments.filter((x) => x.cardId === c.id), pageInfo: {} });
        const x = { id: id(), cardId: c.id, ...body }; comments.push(x); return ok(x, 201);
      }
      return ok(withItems(c));
    }
    if ((r = m(/^\/checklists\/([^/]+)\/items$/))) {
      const l = checklists.find((x) => x.id === r![1]);
      const item = { id: id(), checklistId: l.id, ...body, isDone: false }; l.items.push(item); return ok(item, 201);
    }
    if ((r = m(/^\/checklist-items\/([^/]+)$/))) {
      const item = checklists.flatMap((l) => l.items).find((x) => x.id === r![1]);
      Object.assign(item, body); return ok(item);
    }
    if ((r = m(/^\/comments\/([^/]+)$/))) { const x = comments.find((c) => c.id === r![1]); Object.assign(x, body); return ok(x); }
    if ((r = m(/^\/boards\/([^/]+)\/labels$/))) { const l = { id: id(), boardId: r[1], ...body }; labels.push(l); return ok(l, 201); }
    if (m(/^\/boards\/[^/]+\/activity$/)) return ok({ items: [{ id: 'a1' }], pageInfo: {} });
    if (m(/^\/boards\/[^/]+\/appearance$/)) return ok({ ...body });
    if (path === '/integrations/import-export/exports') return ok({ suggestedFileName: 'board.json', bundle });
    if (path === '/ring') return ok({ enabled: true, ring: null, legacy: [{ publicKey: 'k', approvedAt: at() }] });
    return new Response(JSON.stringify({ error: { message: `нет маршрута ${method} ${path}` } }), { status: 501 });
  };
  return { handler, calls, boards, cards, checklists };
}

describe('web plan against a node in memory', () => {
  it('passes end to end, leaves the cross-client card and removes its own board', async () => {
    const node = fakeNode();
    vi.stubGlobal('fetch', vi.fn(node.handler));
    const style = document.createElement('style');
    style.textContent = readFileSync(join(__dirname, '../../../../app/styles/themes.css'), 'utf8');
    document.head.appendChild(style);
    const ctx = newWebContext(new Date('2026-10-17T03:00:00Z'));
    // An Android card from an earlier phone run waits for its web mark.
    const results1 = await runSteps(webSteps(), ctx);
    const byId = Object.fromEntries(results1.map((r) => [r.id, r]));
    const failed = results1.filter((r) => r.status === 'FAIL').map((r) => `${r.id}: ${r.detail}`);
    expect(failed).toEqual([]);
    expect(byId['auth.poll-limit']!.status).toBe('PASS');
    expect(node.calls.filter((c) => c === 'GET /auth/device-link/lan/inbox')).toHaveLength(60);
    expect(byId['crud.comment']!.detail).toContain(`${new TextEncoder().encode(LONG_COMMENT).length} байт`);
    expect(new TextEncoder().encode(LONG_COMMENT).length).toBeGreaterThan(256);
    expect(byId['io.export']!.status).toBe('PASS');
    expect(byId['ring.view']!.status).toBe('INFO');
    expect(byId['ring.sync']!.status).toBe('SKIP');
    expect(byId['cross.client']!.status).toBe('INFO');
    expect(byId['cleanup']!.status).toBe('PASS');

    const workspace = (await (await fetch('http://127.0.0.1:18080/api/v1/workspaces')).json()).data.items[0];
    expect(workspace.name).toBe(TEST_WORKSPACE);
    const alive = node.boards.filter((b) => !b.deleted).map((b) => b.name);
    expect(alive).toEqual([CROSS_BOARD]);
    const webCard = node.cards.find((c) => c.title.startsWith('web ·'));
    expect(node.checklists.find((l) => l.cardId === webCard.id).items[0].title).toBe(CROSS_ITEM_FOR_ANDROID);

    // The phone marks the web card and leaves its own; the next web run sees both.
    node.checklists.find((l) => l.cardId === webCard.id).items[0].isDone = true;
    const cross = node.boards.find((b) => b.name === CROSS_BOARD);
    node.cards.push({ id: 'android-card', boardId: cross.id, columnId: 'c', title: 'android · 2026-10-17 04:00 · zz', isArchived: false, createdAt: '2026-10-17T04:00:00.000Z' });
    node.checklists.push({ id: 'android-list', cardId: 'android-card', title: 'Встречная проверка', items: [{ id: 'android-item', title: CROSS_ITEM_FOR_WEB, isDone: false }] });
    const results2 = await runSteps(webSteps(), newWebContext(new Date('2026-10-17T05:00:00Z')));
    const crossStep = results2.find((r) => r.id === 'cross.client')!;
    expect(crossStep.status).toBe('PASS');
    expect(crossStep.detail).toContain('Android отметил');
    expect(node.checklists.find((l) => l.id === 'android-list').items[0].isDone).toBe(true);
    expect(node.boards.filter((b) => !b.deleted).map((b) => b.name)).toEqual([CROSS_BOARD]);
  });
});
