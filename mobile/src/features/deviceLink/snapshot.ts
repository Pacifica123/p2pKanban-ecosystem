import type { LocalBoardSnapshot } from '../localFirst/model';
// Portable bundle adapter. A missing local row is not evidence of global deletion.
export function overlayBoard(
  payload: Record<string, any>,
  local: LocalBoardSnapshot,
  deleted: Set<string>,
) {
  const boardId = local.board.id;
  payload.boards ||= [];
  payload.columns ||= [];
  payload.cards ||= [];
  payload.checklists ||= [];
  payload.checklistItems ||= [];
  payload.cardLabels ||= [];
  payload.comments ||= [];
  payload.boardAppearanceSettings ||= [];
  const boards = new Map(payload.boards.map((board: any) => [board.id, board]));
  boards.set(boardId, local.board);
  payload.boards = [...boards.values()];
  const columns = new Map(payload.columns.map((column: any) => [column.id, column]));
  for (const column of local.columns || []) columns.set(column.id, column);
  payload.columns = [...columns.values()];
  const cards = new Map(payload.cards.map((c: any) => [c.id, c]));
  for (const c of local.cards) cards.set(c.id, c);
  for (const id of deleted) cards.delete(id);
  payload.cards = [...cards.values()];
  const hydrated = new Set(
    local.checklistsHydratedAt ? Object.keys(local.checklistsByCardId) : [],
  );
  const replaced = new Set(
    payload.checklists
      .filter((c: any) => hydrated.has(c.cardId) || deleted.has(c.cardId))
      .map((c: any) => c.id),
  );
  const lists = Object.entries(local.checklistsByCardId)
    .filter(([id]) => hydrated.has(id) && !deleted.has(id))
    .flatMap(([, v]) => v);
  payload.checklists = [
    ...payload.checklists.filter(
      (c: any) => !hydrated.has(c.cardId) && !deleted.has(c.cardId),
    ),
    ...lists.map(({ items, ...c }) => c),
  ];
  payload.checklistItems = [
    ...payload.checklistItems.filter((i: any) => !replaced.has(i.checklistId)),
    ...lists.flatMap((l) => l.items),
  ];
  payload.cardLabels = payload.cardLabels.filter(
    (l: any) => !deleted.has(l.cardId),
  );
  payload.comments = payload.comments.filter(
    (c: any) => !deleted.has(c.cardId),
  );
  payload.boardAppearanceSettings = [
    ...payload.boardAppearanceSettings.filter(
      (a: any) => a.boardId !== boardId,
    ),
    { ...local.appearance, boardId },
  ];
  return payload;
}
