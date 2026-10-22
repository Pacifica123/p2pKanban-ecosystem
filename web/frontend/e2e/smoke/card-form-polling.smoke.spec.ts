import { expect, test } from '@playwright/test';
const T = '2026-10-20T10:00:00Z';
const page0 = { nextCursor: null, prevCursor: null, hasNextPage: false, hasPrevPage: false };
// Окно карточки не теряет несохранённый приоритет, когда опрос узла приносит
// изменение другой карточки, и подхватывает правку с другого устройства в поле,
// которое пользователь не трогал (2026-10-22-web-card-form-keeps-edits).
test('card form keeps unsaved priority across board polling', async ({ page }) => {
  test.setTimeout(30_000);
  let tick = 0; let remoteTitle = 'Card k1';
  const patches: unknown[] = [];
  const card = (id: string, extra: Record<string, unknown> = {}) => ({ id, boardId: 'b1', columnId: 'c1', parentCardId: null, title: 'Card ' + id, description: null, priority: null, position: 1, startAt: null, dueAt: null, isArchived: false, labelIds: [], checklistCount: 0, commentCount: 0, createdByUserId: 'user-1', createdAt: T, updatedAt: T, archivedAt: null, ...extra });
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request(); const p = new URL(req.url()).pathname.replace('/api/v1', ''); const m = req.method();
    const ok = (data: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ data }) });
    if (p === '/auth/refresh') return ok({ accessToken: 't', sessionId: 's', deviceId: 'd', user: { id: 'user-1', email: 'a@b.c', displayName: 'U' } });
    if (p === '/workspaces') return ok({ items: [{ id: 'w1', name: 'W', visibility: 'private', ownerUserId: 'user-1', memberCount: 1, currentUserRole: 'owner', isArchived: false, createdAt: T, updatedAt: T }], pageInfo: page0 });
    if (p === '/boards/b1') return ok({ id: 'b1', workspaceId: 'w1', name: 'B', boardType: 'kanban', isArchived: false, createdAt: T, updatedAt: T });
    if (p === '/boards/b1/columns') return ok({ items: [{ id: 'c1', boardId: 'b1', name: 'Todo', position: 1, createdAt: T, updatedAt: T }] });
    if (p === '/boards/b1/appearance') return ok({ boardId: 'b1', isCustomized: false, themePreset: 'default', wallpaper: { kind: 'none', value: null }, columnDensity: 'comfortable', cardPreviewMode: 'expanded', showCardDescription: true, showCardDates: true, showChecklistProgress: true, customProperties: {}, createdAt: T, updatedAt: T });
    if (p === '/me/appearance') return ok({ userId: 'user-1', isCustomized: false, appTheme: 'system', density: 'comfortable', reduceMotion: false, checklistItemSubmitMode: 'ctrl_enter', cardDetailsMode: 'drawer', createdAt: T, updatedAt: T });
    if (p === '/boards/b1/cards') { tick += 1; return ok({ items: [card('k1', { title: remoteTitle }), card('k2', { updatedAt: `2026-10-20T10:00:${String(tick % 60).padStart(2, '0')}Z` })], pageInfo: page0 }); }
    if (p === '/cards/k1' && m === 'GET') return ok(card('k1', { title: remoteTitle }));
    if (p === '/cards/k1' && m === 'PATCH') { patches.push(req.postDataJSON()); return ok(card('k1', req.postDataJSON())); }
    if (m === 'GET') return ok({ items: [], pageInfo: page0 });
    return ok({});
  });
  await page.goto('/workspaces/w1/boards/b1?card=k1');
  const fourth = page.getByRole('button', { name: 'Срочный, 4 из 4' });
  await fourth.click();
  await page.waitForTimeout(4000);
  remoteTitle = 'С телефона';
  await page.waitForTimeout(5000);
  await expect(fourth).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('card-details-dialog').getByLabel('Название')).toHaveValue('С телефона');
  await page.getByRole('button', { name: 'Сохранить карточку' }).click();
  await page.waitForTimeout(1000);
  expect(patches).toEqual([{ title: 'С телефона', description: null, priority: 'urgent' }]);
});
