import { updateBoardAppearance } from '@/features/appearance/api/appearance';
import { createBoard, deleteBoard } from '@/features/boards/api/boards';
import { createCard, updateCard } from '@/features/cards/api/cards';
import { createChecklist, createChecklistItem, updateChecklistItem } from '@/features/checklists/api/checklists';
import { createColumn } from '@/features/columns/api/columns';
import { createComment } from '@/features/comments/api/comments';
import { createBoardLabel, replaceCardLabels } from '@/features/labels/api/labels';
import type { BoardBundleCounts, BoardBundlePreview } from '@/features/integrations/lib/boardBundle';

export interface BoardImportProgress {
  completed: number;
  total: number;
  message: string;
}

export interface BoardImportResult {
  boardId: string;
  boardName: string;
  counts: BoardBundleCounts;
}

export interface BoardImportApi {
  createBoard: typeof createBoard;
  deleteBoard: typeof deleteBoard;
  createColumn: typeof createColumn;
  createCard: typeof createCard;
  updateCard: typeof updateCard;
  createBoardLabel: typeof createBoardLabel;
  replaceCardLabels: typeof replaceCardLabels;
  createChecklist: typeof createChecklist;
  createChecklistItem: typeof createChecklistItem;
  updateChecklistItem: typeof updateChecklistItem;
  createComment: typeof createComment;
  updateBoardAppearance: typeof updateBoardAppearance;
}

interface ImportBoardCopyOptions {
  workspaceId: string;
  boardName: string;
  preview: BoardBundlePreview;
  onProgress?: (progress: BoardImportProgress) => void;
  api?: BoardImportApi;
}

const defaultApi: BoardImportApi = {
  createBoard,
  deleteBoard,
  createColumn,
  createCard,
  updateCard,
  createBoardLabel,
  replaceCardLabels,
  createChecklist,
  createChecklistItem,
  updateChecklistItem,
  createComment,
  updateBoardAppearance,
};

export class BoardImportExecutionError extends Error {
  readonly createdBoardId?: string;
  readonly rollbackSucceeded?: boolean;
  readonly originalCause?: unknown;

  constructor(
    message: string,
    options: { cause?: unknown; createdBoardId?: string; rollbackSucceeded?: boolean } = {},
  ) {
    super(message);
    this.name = 'BoardImportExecutionError';
    this.createdBoardId = options.createdBoardId;
    this.rollbackSucceeded = options.rollbackSucceeded;
    this.originalCause = options.cause;
  }
}

function countOperations(preview: BoardBundlePreview): number {
  const cardsWithPostCreateUpdate = preview.cards.filter(
    (card) => card.parentCardId || card.isArchived,
  ).length;
  const cardsWithLabels = new Set(preview.cardLabels.map((item) => item.cardId)).size;
  return 1
    + preview.columns.length
    + preview.labels.length
    + preview.cards.length
    + cardsWithPostCreateUpdate
    + cardsWithLabels
    + preview.checklists.length
    + preview.checklistItems.length
    + preview.comments.length
    + (preview.appearance ? 1 : 0);
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : 'неизвестная ошибка';
}

export async function importBoardCopy({
  workspaceId,
  boardName,
  preview,
  onProgress,
  api = defaultApi,
}: ImportBoardCopyOptions): Promise<BoardImportResult> {
  const normalizedName = boardName.trim();
  if (!workspaceId) {
    throw new BoardImportExecutionError('Workspace для импорта не выбран.');
  }
  if (!normalizedName) {
    throw new BoardImportExecutionError('Название новой доски не может быть пустым.');
  }

  const total = countOperations(preview);
  let completed = 0;
  let currentStage = 'создание новой доски';
  let createdBoardId: string | undefined;

  const advance = (message: string) => {
    completed += 1;
    currentStage = message;
    onProgress?.({ completed, total, message });
  };

  onProgress?.({ completed: 0, total, message: 'Создаём отдельную копию доски' });

  try {
    const board = await api.createBoard(workspaceId, {
      name: normalizedName,
      description: preview.board.description,
    });
    createdBoardId = board.id;
    advance('Новая доска создана');

    const columnIds = new Map<string, string>();
    for (const [index, column] of preview.columns.entries()) {
      currentStage = `создание колонки ${index + 1}/${preview.columns.length}`;
      const created = await api.createColumn(board.id, {
        name: column.name,
        description: column.description,
        position: column.position,
        colorToken: column.colorToken,
        wipLimit: column.wipLimit,
      });
      columnIds.set(column.id, created.id);
      advance(`Колонки: ${index + 1}/${preview.columns.length}`);
    }

    const labelIds = new Map<string, string>();
    for (const [index, label] of preview.labels.entries()) {
      currentStage = `создание метки ${index + 1}/${preview.labels.length}`;
      const created = await api.createBoardLabel(board.id, {
        name: label.name,
        color: label.color,
        description: label.description,
      });
      labelIds.set(label.id, created.id);
      advance(`Метки: ${index + 1}/${preview.labels.length}`);
    }

    const cardIds = new Map<string, string>();
    for (const [index, card] of preview.cards.entries()) {
      currentStage = `создание карточки ${index + 1}/${preview.cards.length}`;
      const targetColumnId = columnIds.get(card.columnId);
      if (!targetColumnId) {
        throw new Error(`для карточки ${card.title} не создана колонка`);
      }
      const created = await api.createCard(board.id, {
        title: card.title,
        description: card.description,
        columnId: targetColumnId,
        position: card.position,
        priority: card.priority || undefined,
        startAt: card.startAt,
        dueAt: card.dueAt,
      });
      cardIds.set(card.id, created.id);
      advance(`Карточки: ${index + 1}/${preview.cards.length}`);
    }

    const cardsWithUpdates = preview.cards.filter(
      (card) => card.parentCardId || card.isArchived,
    );
    for (const [index, card] of cardsWithUpdates.entries()) {
      currentStage = `восстановление свойств карточки ${index + 1}/${cardsWithUpdates.length}`;
      const targetCardId = cardIds.get(card.id);
      if (!targetCardId) throw new Error(`не найдено соответствие карточки ${card.id}`);
      const parentCardId = card.parentCardId ? cardIds.get(card.parentCardId) : undefined;
      if (card.parentCardId && !parentCardId) {
        throw new Error(`не найден родитель карточки ${card.title}`);
      }
      await api.updateCard(targetCardId, {
        parentCardId,
        isArchived: card.isArchived || undefined,
      });
      advance(`Свойства карточек: ${index + 1}/${cardsWithUpdates.length}`);
    }

    const labelsByCard = new Map<string, Set<string>>();
    for (const relation of preview.cardLabels) {
      const values = labelsByCard.get(relation.cardId) || new Set<string>();
      values.add(relation.labelId);
      labelsByCard.set(relation.cardId, values);
    }
    for (const [index, [sourceCardId, sourceLabelIds]] of [...labelsByCard.entries()].entries()) {
      currentStage = `назначение меток ${index + 1}/${labelsByCard.size}`;
      const targetCardId = cardIds.get(sourceCardId);
      if (!targetCardId) throw new Error(`не найдено соответствие карточки ${sourceCardId}`);
      const targetLabelIds = [...sourceLabelIds].map((sourceLabelId) => {
        const targetLabelId = labelIds.get(sourceLabelId);
        if (!targetLabelId) throw new Error(`не найдено соответствие метки ${sourceLabelId}`);
        return targetLabelId;
      });
      await api.replaceCardLabels(targetCardId, targetLabelIds);
      advance(`Связи с метками: ${index + 1}/${labelsByCard.size}`);
    }

    const checklistIds = new Map<string, string>();
    for (const [index, checklist] of preview.checklists.entries()) {
      currentStage = `создание checklist ${index + 1}/${preview.checklists.length}`;
      const targetCardId = cardIds.get(checklist.cardId);
      if (!targetCardId) throw new Error(`не найдено соответствие карточки ${checklist.cardId}`);
      const created = await api.createChecklist(targetCardId, {
        title: checklist.title,
        position: checklist.position,
      });
      checklistIds.set(checklist.id, created.id);
      advance(`Checklists: ${index + 1}/${preview.checklists.length}`);
    }

    for (const [index, item] of preview.checklistItems.entries()) {
      currentStage = `создание пункта checklist ${index + 1}/${preview.checklistItems.length}`;
      const targetChecklistId = checklistIds.get(item.checklistId);
      if (!targetChecklistId) throw new Error(`не найдено соответствие checklist ${item.checklistId}`);
      const created = await api.createChecklistItem(targetChecklistId, {
        title: item.title,
        position: item.position,
      });
      if (item.isDone) {
        await api.updateChecklistItem(created.id, { isDone: true });
      }
      advance(`Пункты checklist: ${index + 1}/${preview.checklistItems.length}`);
    }

    for (const [index, comment] of preview.comments.entries()) {
      currentStage = `создание комментария ${index + 1}/${preview.comments.length}`;
      const targetCardId = cardIds.get(comment.cardId);
      if (!targetCardId) throw new Error(`не найдено соответствие карточки ${comment.cardId}`);
      await api.createComment(targetCardId, { body: comment.body });
      advance(`Комментарии: ${index + 1}/${preview.comments.length}`);
    }

    if (preview.appearance) {
      currentStage = 'восстановление оформления';
      await api.updateBoardAppearance(board.id, preview.appearance);
      advance('Оформление восстановлено');
    }

    return {
      boardId: board.id,
      boardName: board.name,
      counts: preview.counts,
    };
  } catch (error) {
    if (!createdBoardId) {
      throw new BoardImportExecutionError(
        `Импорт остановлен на этапе «${currentStage}»: ${messageFromError(error)}.`,
        { cause: error },
      );
    }

    try {
      await api.deleteBoard(createdBoardId);
      throw new BoardImportExecutionError(
        `Импорт остановлен на этапе «${currentStage}»: ${messageFromError(error)}. Недособранная копия удалена.`,
        { cause: error, createdBoardId, rollbackSucceeded: true },
      );
    } catch (rollbackError) {
      if (rollbackError instanceof BoardImportExecutionError) throw rollbackError;
      throw new BoardImportExecutionError(
        `Импорт остановлен на этапе «${currentStage}»: ${messageFromError(error)}. Автоматически удалить недособранную доску ${createdBoardId} не удалось: ${messageFromError(rollbackError)}.`,
        { cause: error, createdBoardId, rollbackSucceeded: false },
      );
    }
  }
}
