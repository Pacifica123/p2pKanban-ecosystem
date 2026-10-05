import { expect, test } from '@playwright/test';

function uniqueSuffix() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

test('real backend core kanban path uses API without mocks', async ({ page }) => {
  const apiBaseUrl = (process.env.VITE_API_BASE_URL || 'http://127.0.0.1:18080/api/v1').replace(/\/$/, '');
  const suffix = uniqueSuffix();
  const email = `real-browser-smoke-${suffix}@local.test`;
  const password = `Password-${suffix}!`;
  const workspaceName = `Real Backend Workspace ${suffix}`;
  const boardName = `Real Backend Board ${suffix}`;
  const columnName = `Todo ${suffix}`;
  const cardName = `Real Backend Card ${suffix}`;
  const pageErrors: string[] = [];
  const apiRequests: string[] = [];

  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (request.url().startsWith(apiBaseUrl)) {
      const url = new URL(request.url());
      apiRequests.push(`${request.method()} ${url.pathname}`);
    }
  });

  await page.goto('/auth');
  await page.getByRole('button', { name: 'Зарегистрироваться' }).click();
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Пароль').fill(password);
  await page.getByLabel('Имя').fill('Real Browser Smoke');
  await page.locator('form').getByRole('button', { name: 'Создать аккаунт' }).click();

  await expect(page.getByRole('heading', { name: 'Рабочие пространства' })).toBeVisible();

  await page.getByLabel('Название').fill(workspaceName);
  await page.getByLabel('Описание').fill('Created by the real-backend browser smoke gate.');
  await page.getByRole('button', { name: 'Создать пространство' }).click();

  await expect(page.getByRole('heading', { name: 'Новая доска' })).toBeVisible();
  await page.getByLabel('Название').fill(boardName);
  await page.getByLabel('Описание').fill('Created without Playwright API mocks.');
  await page.getByRole('button', { name: 'Создать доску' }).click();

  await expect(page.getByRole('heading', { name: boardName })).toBeVisible();
  await page.getByRole('button', { name: 'Создать колонку' }).click();
  await page.getByLabel('Название новой колонки').fill(columnName);
  await page.getByRole('button', { name: 'Добавить' }).click();

  const createdColumn = page
    .locator('.column-card')
    .filter({ has: page.getByRole('heading', { name: columnName }) });
  await expect(createdColumn.getByRole('heading', { name: columnName })).toBeVisible();

  await createdColumn.getByPlaceholder('Добавить карточку').fill(cardName);
  await createdColumn.getByRole('button', { name: 'Добавить карточку' }).click();
  await expect(createdColumn.locator('.card-tile').filter({ hasText: cardName })).toBeVisible();

  await expect.poll(() => pageErrors).toEqual([]);
  expect(apiRequests.some((entry) => entry.includes('/api/v1/auth/sign-up'))).toBeTruthy();
  expect(apiRequests.some((entry) => entry.includes('/api/v1/workspaces'))).toBeTruthy();
  expect(apiRequests.some((entry) => entry.includes('/api/v1/boards'))).toBeTruthy();
  expect(apiRequests.some((entry) => /\/api\/v1\/boards\/[^/]+\/columns/.test(entry))).toBeTruthy();
  expect(apiRequests.some((entry) => /\/api\/v1\/boards\/[^/]+\/cards/.test(entry))).toBeTruthy();
});
