import { beforeEach, expect, test, vi } from 'vitest';
import {
  deleteCard,
  getCards,
  hideCardLocally,
  unhideCardLocally,
} from '@/features/cards/api/cards';
import { apiRequest } from '@/shared/api/client';

vi.mock('@/shared/api/client', () => ({
  apiRequest: vi.fn().mockResolvedValue({}),
}));

beforeEach(() => {
  vi.mocked(apiRequest).mockClear();
});

test('local visibility uses a node-only API surface', async () => {
  await getCards('board-1', 'hidden');
  await hideCardLocally('card-1');
  await unhideCardLocally('card-1');

  expect(apiRequest).toHaveBeenNthCalledWith(
    1,
    '/boards/board-1/cards?localVisibility=hidden',
  );
  expect(apiRequest).toHaveBeenNthCalledWith(
    2,
    '/cards/card-1/hide-local',
    { method: 'POST' },
  );
  expect(apiRequest).toHaveBeenNthCalledWith(
    3,
    '/cards/card-1/hide-local',
    { method: 'DELETE' },
  );
});

test('global delete declares all_devices scope explicitly', async () => {
  await deleteCard('card-1');
  expect(apiRequest).toHaveBeenCalledWith(
    '/cards/card-1?scope=all_devices',
    { method: 'DELETE' },
  );
});
