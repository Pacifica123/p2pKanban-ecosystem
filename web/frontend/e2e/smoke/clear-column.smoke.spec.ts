import { expect, test } from '@playwright/test';
const T = '2026-10-20T10:00:00Z';
const page0 = { nextCursor: null, prevCursor: null, hasNextPage: false, hasPrevPage: false };
// «Удалить все карточки колонки» спрашивает подтверждение, удаляет карточки только
// этой колонки (архивные тоже) обычным DELETE …?scope=all_devices и не трогает
// соседние колонки (2026-10-22-web-clear-column).
test('clear one column after confirmation', async ({ page }, info) => {
  test.setTimeout(30_000);
  const card = (id: string, columnId: string, extra: Record<string, unknown> = {}) => ({ id, boardId: 'b1', columnId, parentCardId: null, title: 'Card ' + id, description: null, priority: null, position: 1, startAt: null, dueAt: null, isArchived: false, labelIds: [], checklistCount: 0, commentCount: 0, createdByUserId: 'user-1', createdAt: T, updatedAt: T, archivedAt: null, ...extra });
  let cards = [card('t1', 'todo'), card('d1', 'done'), card('d2', 'done', { isArchived: true, archivedAt: T })];
  const deletes: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request(); const url = new URL(req.url()); const p = url.pathname.replace('/api/v1', ''); const m = req.method();
    const ok = (data: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data }) });
    if (p === '/auth/refresh') return ok({ accessToken: 't', sessionId: 's', deviceId: 'd', user: { id: 'user-1', email: 'a@b.c', displayName: 'U' } });
    if (p === '/workspaces') return ok({ items: [{ id: 'w1', name: 'W', visibility: 'private', ownerUserId: 'user-1', memberCount: 1, currentUserRole: 'owner', isArchived: false, createdAt: T, updatedAt: T }], pageInfo: page0 });
    if (p === '/boards/b1') return ok({ id: 'b1', workspaceId: 'w1', name: 'B', boardType: 'kanban', isArchived: false, createdAt: T, updatedAt: T });
    if (p === '/boards/b1/columns') return ok({ items: [{ id: 'todo', boardId: 'b1', name: 'Сделать', position: 1, createdAt: T, updatedAt: T }, { id: 'done', boardId: 'b1', name: 'Готово', position: 2, createdAt: T, updatedAt: T }] });
    if (p === '/boards/b1/appearance') return ok({ boardId: 'b1', isCustomized: false, themePreset: 'default', wallpaper: { kind: 'none', value: null }, columnDensity: 'comfortable', cardPreviewMode: 'expanded', showCardDescription: true, showCardDates: true, showChecklistProgress: true, customProperties: {}, createdAt: T, updatedAt: T });
    if (p === '/me/appearance') return ok({ userId: 'user-1', isCustomized: false, appTheme: 'system', density: 'comfortable', reduceMotion: false, checklistItemSubmitMode: 'ctrl_enter', cardDetailsMode: 'drawer', createdAt: T, updatedAt: T });
    if (p === '/boards/b1/cards') return ok({ items: url.searchParams.get('localVisibility') === 'hidden' ? [] : cards, pageInfo: page0 });
    const del = p.match(/^\/cards\/([^/]+)$/);
    if (del && m === 'DELETE') {
      expect(url.searchParams.get('scope')).toBe('all_devices');
      deletes.push(del[1]!); cards = cards.filter((item) => item.id !== del[1]);
      return ok(card(del[1]!, 'done'));
    }
    if (m === 'GET') return ok({ items: [], pageInfo: page0 });
    return ok({});
  });
  await page.goto('/workspaces/w1/boards/b1');
  const done = page.getByTestId('board-column').filter({ hasText: 'Готово' });
  const todo = page.getByTestId('board-column').filter({ hasText: 'Сделать' });
  await expect(done.getByText('2 карточки')).toBeVisible();
  // «Отмена» в подтверждении ничего не удаляет.
  page.once('dialog', (dialog) => dialog.dismiss());
  await done.getByTestId('column-clear').click();
  await page.waitForTimeout(300);
  expect(deletes).toEqual([]);
  let question = '';
  page.once('dialog', (dialog) => { question = dialog.message(); void dialog.accept(); });
  await done.getByTestId('column-clear').click();
  await expect(page.getByText('Колонка «Готово» очищена: удалено 2 карточки.')).toBeVisible();
  expect(question).toContain('Удалить 2 карточки из колонки «Готово» на всех устройствах?');
  expect(deletes.sort()).toEqual(['d1', 'd2']);
  await expect(done.getByText('0 карточек')).toBeVisible();
  await expect(done.getByTestId('column-clear')).toHaveCount(0);
  await expect(todo.getByText('1 карточка')).toBeVisible();
  await page.screenshot({ path: info.outputPath('cleared.png'), fullPage: true });
});
