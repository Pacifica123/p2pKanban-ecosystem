import fixture from '@/test/fixtures/board-backup-v1.json';
import { parseBoardBundleText } from '@/features/integrations/lib/boardBundle';
import {
  BoardImportApi,
  BoardImportExecutionError,
  importBoardCopy,
} from '@/features/integrations/lib/importBoardCopy';

function response(id: string, extra: Record<string, unknown> = {}) {
  return Promise.resolve({ id, ...extra } as any);
}

function makeApi(): BoardImportApi {
  return {
    createBoard: vi.fn(async (_workspaceId, input) => response('board-new', { name: input.name })),
    deleteBoard: vi.fn(async () => response('board-new')),
    createColumn: vi.fn(async (_boardId, input) => response(`new-${input.name}`)),
    createCard: vi.fn(async (_boardId, input) => response(`new-${input.title}`)),
    updateCard: vi.fn(async (cardId) => response(cardId)),
    createBoardLabel: vi.fn(async (_boardId, input) => response(`new-label-${input.name}`)),
    replaceCardLabels: vi.fn(async (cardId) => response(cardId)),
    createChecklist: vi.fn(async (_cardId, input) => response(`new-checklist-${input.title}`)),
    createChecklistItem: vi.fn(async (_checklistId, input) => response(`new-item-${input.title}`)),
    updateChecklistItem: vi.fn(async (itemId) => response(itemId)),
    createComment: vi.fn(async (_cardId, input) => response(`new-comment-${input.body}`)),
    updateBoardAppearance: vi.fn(async (boardId) => response(boardId)),
  } as BoardImportApi;
}

describe('board copy importer', () => {
  it('recreates relationships with new server IDs', async () => {
    const api = makeApi();
    const preview = parseBoardBundleText(JSON.stringify(fixture));

    const result = await importBoardCopy({
      workspaceId: 'workspace-new',
      boardName: 'Imported release plan',
      preview,
      api,
    });

    expect(result.boardId).toBe('board-new');
    expect(api.createBoard).toHaveBeenCalledWith('workspace-new', {
      name: 'Imported release plan',
      description: 'Fixture for board import',
    });
    expect(api.createCard).toHaveBeenCalledWith(
      'board-new',
      expect.objectContaining({
        title: 'Prepare release',
        columnId: 'new-Todo',
      }),
    );
    expect(api.updateCard).toHaveBeenCalledWith(
      'new-Write notes',
      expect.objectContaining({
        parentCardId: 'new-Prepare release',
        isArchived: true,
      }),
    );
    expect(api.replaceCardLabels).toHaveBeenCalledWith(
      'new-Prepare release',
      ['new-label-release'],
    );
    expect(api.updateChecklistItem).toHaveBeenCalledWith('new-item-Documentation', { isDone: true });
    expect(api.updateBoardAppearance).toHaveBeenCalledWith(
      'board-new',
      expect.objectContaining({ themePreset: 'plum-ink' }),
    );
    expect(api.deleteBoard).not.toHaveBeenCalled();
  });

  it('removes only the newly created partial board when a later step fails', async () => {
    const api = makeApi();
    vi.mocked(api.createCard).mockRejectedValueOnce(new Error('backend unavailable'));
    const preview = parseBoardBundleText(JSON.stringify(fixture));

    await expect(importBoardCopy({
      workspaceId: 'workspace-new',
      boardName: 'Broken import',
      preview,
      api,
    })).rejects.toMatchObject<Partial<BoardImportExecutionError>>({
      createdBoardId: 'board-new',
      rollbackSucceeded: true,
    });

    expect(api.deleteBoard).toHaveBeenCalledWith('board-new');
  });
});
