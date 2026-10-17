// contracts/project-board/1: a read-only view of the portable board file.

export interface ProjectBoardLabel { name: string; color: string }
export interface ProjectBoardChecklist { id: string; title: string; items: { id: string; title: string; isDone: boolean }[] }
export interface ProjectBoardComment { id: string; body: string; createdAt: string }
export interface ProjectBoardCard {
  id: string;
  title: string;
  description: string;
  labels: ProjectBoardLabel[];
  checklists: ProjectBoardChecklist[];
  comments: ProjectBoardComment[];
  done: number;
  total: number;
}
export interface ProjectBoardColumn { id: string; name: string; cards: ProjectBoardCard[] }

type Row = Record<string, unknown>;

function rows(payload: Row, key: string): Row[] {
  const value = payload[key];
  return Array.isArray(value) ? value.filter((row): row is Row => Boolean(row) && typeof row === 'object') : [];
}

const text = (value: unknown) => (typeof value === 'string' ? value : '');
const position = (row: Row) => (typeof row.position === 'number' ? row.position : 0);
const byPosition = (a: Row, b: Row) => position(a) - position(b);

export function projectBoardColumns(raw: string): ProjectBoardColumn[] {
  const bundle = JSON.parse(raw) as Row;
  const payload = (bundle.payload ?? {}) as Row;
  const labels = new Map(rows(payload, 'labels').map((l) => [text(l.id), { name: text(l.name), color: text(l.color) || '#888' }]));
  const items = rows(payload, 'checklistItems').sort(byPosition);
  const checklists = rows(payload, 'checklists').sort(byPosition).map((c) => ({
    cardId: text(c.cardId),
    view: {
      id: text(c.id),
      title: text(c.title),
      items: items.filter((i) => i.checklistId === c.id).map((i) => ({ id: text(i.id), title: text(i.title), isDone: i.isDone === true })),
    },
  }));
  const comments = rows(payload, 'comments');
  const cardLabels = rows(payload, 'cardLabels');
  const cards = rows(payload, 'cards').filter((c) => !c.archivedAt).sort(byPosition).map((c) => {
    const own = checklists.filter((cl) => cl.cardId === c.id).map((cl) => cl.view);
    const all = own.flatMap((cl) => cl.items);
    return {
      columnId: text(c.columnId),
      view: {
        id: text(c.id),
        title: text(c.title),
        description: text(c.description),
        labels: cardLabels.filter((cl) => cl.cardId === c.id).map((cl) => labels.get(text(cl.labelId))).filter((l): l is ProjectBoardLabel => Boolean(l)),
        checklists: own,
        comments: comments.filter((m) => m.cardId === c.id).map((m) => ({ id: text(m.id), body: text(m.body), createdAt: text(m.createdAt) })),
        done: all.filter((i) => i.isDone).length,
        total: all.length,
      },
    };
  });
  return rows(payload, 'columns').sort(byPosition).map((col) => ({
    id: text(col.id),
    name: text(col.name),
    cards: cards.filter((c) => c.columnId === col.id).map((c) => c.view),
  }));
}

export function projectBoardLine(board: { revision: string; lastPatchId: string; source: string }): string {
  const where = board.source === 'build' ? 'из сборки' : 'с узла';
  return `Ревизия ${board.revision} · ${board.lastPatchId} · ${where}`;
}
