import { createBoard, getBoards } from '@/features/boards/api/boards';
import { createCard, getCards, updateCard } from '@/features/cards/api/cards';
import { createColumn, getColumns } from '@/features/columns/api/columns';
import {
  ensureProjectRoadmapSeed,
  ROADMAP_CARDS,
} from '@/features/bootstrap/lib/projectRoadmapSeed';
import { createWorkspace, getWorkspaces } from '@/features/workspaces/api/workspaces';

vi.mock('@/features/boards/api/boards', () => ({
  createBoard: vi.fn(),
  getBoards: vi.fn(),
}));
vi.mock('@/features/cards/api/cards', () => ({
  createCard: vi.fn(),
  getCards: vi.fn(),
  updateCard: vi.fn(),
}));
vi.mock('@/features/columns/api/columns', () => ({
  createColumn: vi.fn(),
  getColumns: vi.fn(),
}));
vi.mock('@/features/workspaces/api/workspaces', () => ({
  createWorkspace: vi.fn(),
  getWorkspaces: vi.fn(),
}));

const columns = ['Готово', 'Сейчас', 'Далее', 'Потом'].map((name, index) => ({
  id: `column-${index}`,
  boardId: 'board-roadmap',
  name,
  description: null,
  position: index * 1000,
  createdAt: '2026-08-23T00:00:00Z',
  updatedAt: '2026-08-23T00:00:00Z',
}));

describe('project roadmap seed v2', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getWorkspaces).mockResolvedValue({
      items: [{ id: 'workspace-roadmap', name: 'P2P Planner roadmap', isArchived: false }],
    } as any);
    vi.mocked(getBoards).mockResolvedValue({
      items: [{ id: 'board-roadmap', name: 'План работ по проекту', isArchived: false }],
    } as any);
    vi.mocked(getColumns).mockResolvedValue({ items: columns } as any);
    vi.mocked(getCards).mockResolvedValue({
      items: [{
        id: 'legacy-local-first',
        boardId: 'board-roadmap',
        columnId: 'column-2',
        title: 'Local-first слой',
        description: 'Старое описание',
        priority: 'high',
        position: 1000,
        isArchived: false,
        createdAt: '2026-01-01T00:00:00Z',
        updatedAt: '2026-01-01T00:00:00Z',
      }],
    } as any);
    vi.mocked(updateCard).mockImplementation(async (id, input) => ({
      id,
      boardId: 'board-roadmap',
      columnId: input.columnId || 'column-0',
      title: id,
      description: input.description,
      priority: input.priority ?? null,
    } as any));
    vi.mocked(createCard).mockImplementation(async (_boardId, input) => ({
      id: `created-${input.title}`,
      boardId: 'board-roadmap',
      position: 1000,
      isArchived: false,
      createdAt: '2026-08-23T00:00:00Z',
      updatedAt: '2026-08-23T00:00:00Z',
      ...input,
    } as any));
  });

  it('updates the existing demonstration board and prioritizes v2 plans', async () => {
    await ensureProjectRoadmapSeed();

    expect(createWorkspace).not.toHaveBeenCalled();
    expect(createBoard).not.toHaveBeenCalled();
    expect(createColumn).not.toHaveBeenCalled();
    expect(updateCard).toHaveBeenCalledWith('legacy-local-first', expect.objectContaining({
      columnId: 'column-0',
      priority: null,
    }));
    expect(createCard).toHaveBeenCalledWith('board-roadmap', expect.objectContaining({
      title: 'v2: Пригласительные ссылки и права доступа',
      columnId: 'column-0',
      priority: null,
    }));
    expect(createCard).toHaveBeenCalledWith('board-roadmap', expect.objectContaining({
      title: 'v2: Интеграция с Obsidian',
      columnId: 'column-3',
      priority: 'medium',
    }));
  });

  it('contains every requested v2 direction exactly once', () => {
    const titles = Object.values(ROADMAP_CARDS).flat().map((seed) => seed.title);
    for (const expected of ['Rich text', 'devctl', 'GitHub', 'Obsidian', 'Пригласительные ссылки']) {
      expect(titles.filter((title) => title.includes(expected))).toHaveLength(1);
    }
  });
});
