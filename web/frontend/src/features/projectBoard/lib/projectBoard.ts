import type { BoardBundlePreview, ImportedCardSource } from '@/features/integrations/lib/boardBundle';

export const PROJECT_BOARD_PROTOCOL = 'p2p-kanban-project-board/1';
export const PROJECT_BOARD_ID = '01a10d38-f902-7665-8612-3e74278ceafa';

export interface ProjectBoardSummary {
  protocol: typeof PROJECT_BOARD_PROTOCOL;
  boardId: string;
  revision: number;
  lastPatchId: string;
  generatedAt: string | null;
  sha256: string;
  bytes: number;
}

export interface ProjectBoardNodeSummary {
  protocol: typeof PROJECT_BOARD_PROTOCOL;
  served: { source: 'build' | 'upstream'; summary: ProjectBoardSummary };
  build: ProjectBoardSummary;
  upstream: {
    enabled: boolean;
    url: string | null;
    checkedAt: string | null;
    summary: ProjectBoardSummary | null;
    error: string | null;
  };
}

const SOURCE_LABEL = { build: 'из сборки узла', upstream: 'с GitHub (main)' } as const;

/** «Ревизия 33 · <patchId> · с GitHub (main)» and the notes under it. */
export function describeProjectBoard(summary: ProjectBoardNodeSummary): { line: string; notes: string[] } {
  const { served, build, upstream } = summary;
  const line = `Ревизия ${served.summary.revision} · ${served.summary.lastPatchId} · ${SOURCE_LABEL[served.source]}`;
  const notes: string[] = [];
  if (served.source === 'upstream' && build.revision < served.summary.revision) {
    notes.push(`В сборке узла ревизия ${build.revision}: на GitHub уже новее, узел показывает её без пересборки.`);
  }
  if (served.source === 'build' && upstream.summary && upstream.summary.revision < build.revision) {
    notes.push(`На GitHub ревизия ${upstream.summary.revision}: сборка узла новее.`);
  }
  if (!upstream.enabled) {
    notes.push('Проверка GitHub выключена на узле (P2PKANBAN_PROJECT_BOARD_UPSTREAM=off).');
  } else if (upstream.error) {
    notes.push(`GitHub не проверен: ${upstream.error}. Показана самая новая известная узлу ревизия.`);
  } else if (!upstream.checkedAt) {
    notes.push('GitHub ещё не проверялся после запуска узла.');
  }
  if (upstream.summary && upstream.summary.revision === build.revision && upstream.summary.sha256 !== build.sha256) {
    notes.push(`Две разные доски ревизии ${build.revision}: в сборке и на GitHub. Показана одна из них по правилу контракта.`);
  }
  return { line, notes };
}

export interface ProjectBoardColumnView {
  id: string;
  name: string;
  description?: string;
  cards: ImportedCardSource[];
}

/** Columns in board order, cards by position; archived cards are left out. */
export function projectBoardColumns(preview: BoardBundlePreview): ProjectBoardColumnView[] {
  const byColumn = new Map<string, ImportedCardSource[]>();
  for (const card of preview.cards) {
    if (card.isArchived) continue;
    const list = byColumn.get(card.columnId) ?? [];
    list.push(card);
    byColumn.set(card.columnId, list);
  }
  return [...preview.columns]
    .sort((a, b) => a.position - b.position)
    .map((column) => ({
      id: column.id,
      name: column.name,
      description: column.description,
      cards: (byColumn.get(column.id) ?? []).sort((a, b) => a.position - b.position),
    }));
}

export function cardLabels(preview: BoardBundlePreview, cardId: string) {
  const ids = new Set(preview.cardLabels.filter((edge) => edge.cardId === cardId).map((edge) => edge.labelId));
  return preview.labels.filter((label) => ids.has(label.id));
}

export function cardChecklists(preview: BoardBundlePreview, cardId: string) {
  return preview.checklists
    .filter((checklist) => checklist.cardId === cardId)
    .sort((a, b) => a.position - b.position)
    .map((checklist) => ({
      ...checklist,
      items: preview.checklistItems
        .filter((item) => item.checklistId === checklist.id)
        .sort((a, b) => a.position - b.position),
    }));
}

export function cardProgress(preview: BoardBundlePreview, cardId: string) {
  const items = cardChecklists(preview, cardId).flatMap((checklist) => checklist.items);
  if (!items.length) return null;
  const done = items.filter((item) => item.isDone).length;
  return { done, total: items.length, percent: Math.round((done / items.length) * 100) };
}

export function cardComments(preview: BoardBundlePreview, cardId: string) {
  return preview.comments
    .filter((comment) => comment.cardId === cardId)
    .sort((a, b) => String(a.createdAt ?? '').localeCompare(String(b.createdAt ?? '')));
}
