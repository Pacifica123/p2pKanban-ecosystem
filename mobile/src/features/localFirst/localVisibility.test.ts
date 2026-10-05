import type { Card } from '../../shared/types/api';
import {
  applyLocalCardVisibility,
  type LocallyHiddenCard,
} from './localVisibility';
import { LOCAL_SCHEMA_VERSION, type LocalBoardSnapshot } from './model';
import { defaultBoardAppearance } from '../appearance/boardTheme';

jest.mock('../../shared/storage/storage', () => ({
  readSessionJson: jest.fn(),
  writeSessionJson: jest.fn(),
}));

const card: Card = {
  id: 'card-hidden-here',
  boardId: 'board-one',
  columnId: 'column-one',
  title: 'Локальная страховочная копия',
  priority: null,
  position: 1000,
  isArchived: false,
  createdAt: '2026-08-01T10:00:00.000Z',
  updatedAt: '2026-08-01T10:00:00.000Z',
};

const snapshot: LocalBoardSnapshot = {
  schemaVersion: LOCAL_SCHEMA_VERSION,
  workspaceId: 'workspace-one',
  board: {
    id: card.boardId,
    workspaceId: 'workspace-one',
    name: 'Доска',
    boardType: 'kanban',
    isArchived: false,
    createdAt: card.createdAt,
    updatedAt: card.updatedAt,
  },
  appearance: defaultBoardAppearance(card.boardId),
  columns: [],
  cards: [card],
  checklistsByCardId: { [card.id]: [] },
  checklistsHydratedAt: card.updatedAt,
  cachedAt: card.updatedAt,
  lastServerRefreshAt: card.updatedAt,
};

test('node-local visibility removes only the local projection and its checklists', () => {
  const hidden: LocallyHiddenCard[] = [{
    card,
    checklists: [],
    hiddenAt: '2026-08-01T11:00:00.000Z',
  }];

  const result = applyLocalCardVisibility(snapshot, hidden);

  expect(result.cards).toEqual([]);
  expect(result.checklistsByCardId[card.id]).toBeUndefined();
  expect(snapshot.cards).toEqual([card]);
});
