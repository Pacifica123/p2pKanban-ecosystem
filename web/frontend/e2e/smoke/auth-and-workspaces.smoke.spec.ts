import { expect, test } from '@playwright/test';

test('auth boot and workspace list smoke path stays alive', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.route('**/api/v1/auth/refresh', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({
        error: {
          code: 'unauthorized',
          message: 'Unauthorized',
        },
      }),
    });
  });

  await page.route('**/api/v1/auth/sign-in', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          accessToken: 'browser-smoke-token',
          sessionId: 'session-1',
          deviceId: 'device-1',
          user: {
            id: 'user-1',
            email: 'smoke-user@local.test',
            displayName: 'Smoke User',
          },
        },
      }),
    });
  });


  await page.route('**/api/v1/me/appearance', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          userId: 'user-1',
          isCustomized: false,
          appTheme: 'system',
          density: 'comfortable',
          reduceMotion: false,
          checklistItemSubmitMode: 'ctrl_enter',
          cardDetailsMode: 'drawer',
          createdAt: '2026-04-14T10:00:00Z',
          updatedAt: '2026-04-14T10:00:00Z',
        },
      }),
    });
  });

  await page.route('**/api/v1/workspaces', async (route) => {
    const request = route.request();
    if (request.method() !== 'GET') {
      await route.abort();
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          items: [
            {
              id: 'workspace-1',
              name: 'Browser Smoke Workspace',
              slug: null,
              description: 'Short mocked workspace list for browser smoke.',
              visibility: 'private',
              ownerUserId: 'user-1',
              memberCount: 1,
              isArchived: false,
              createdAt: '2026-04-14T10:00:00Z',
              updatedAt: '2026-04-14T10:10:00Z',
              archivedAt: null,
            },
          ],
          pageInfo: {
            nextCursor: null,
            prevCursor: null,
            hasNextPage: false,
            hasPrevPage: false,
          },
        },
      }),
    });
  });

  await page.goto('/auth');

  await page.getByLabel('Email').fill('smoke-user@local.test');
  await page.getByLabel('Пароль').fill('password123');
  await page.locator('form').getByRole('button', { name: 'Войти' }).click();

  await expect(page.getByRole('heading', { name: 'Рабочие пространства' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Browser Smoke Workspace' })).toBeVisible();
  await expect.poll(() => pageErrors).toEqual([]);
});
