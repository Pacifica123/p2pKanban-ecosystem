import type { CardPriority, UpdateBoardAppearanceRequest } from '@/shared/types/api';

export const BOARD_BUNDLE_FORMAT = 'p2p_planner_bundle';
export const BOARD_BUNDLE_FORMAT_VERSION = 1;
export const MAX_BOARD_BUNDLE_SIZE_BYTES = 10 * 1024 * 1024;

type JsonObject = Record<string, unknown>;

export interface ImportedBoardSource {
  id: string;
  name: string;
  description?: string;
  isArchived: boolean;
}

export interface ImportedColumnSource {
  id: string;
  name: string;
  description?: string;
  position: number;
  colorToken?: string;
  wipLimit?: number;
}

export interface ImportedCardSource {
  id: string;
  columnId: string;
  parentCardId?: string;
  title: string;
  description?: string;
  priority: CardPriority;
  position: number;
  startAt?: string;
  dueAt?: string;
  isArchived: boolean;
}

export interface ImportedLabelSource {
  id: string;
  name: string;
  color: string;
  description?: string;
}

export interface ImportedCardLabelSource {
  cardId: string;
  labelId: string;
}

export interface ImportedChecklistSource {
  id: string;
  cardId: string;
  title: string;
  position: number;
}

export interface ImportedChecklistItemSource {
  id: string;
  checklistId: string;
  title: string;
  isDone: boolean;
  position: number;
}

export interface ImportedCommentSource {
  id: string;
  cardId: string;
  body: string;
  createdAt?: string;
}

export interface BoardBundleCounts {
  columns: number;
  cards: number;
  labels: number;
  checklists: number;
  checklistItems: number;
  comments: number;
}

export interface BoardBundlePreview {
  fileName: string;
  bundleKind: 'portable_export' | 'backup_snapshot';
  generatedAt?: string;
  board: ImportedBoardSource;
  columns: ImportedColumnSource[];
  cards: ImportedCardSource[];
  labels: ImportedLabelSource[];
  cardLabels: ImportedCardLabelSource[];
  checklists: ImportedChecklistSource[];
  checklistItems: ImportedChecklistItemSource[];
  comments: ImportedCommentSource[];
  appearance?: UpdateBoardAppearanceRequest;
  counts: BoardBundleCounts;
  warnings: string[];
}

export class BoardBundleValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BoardBundleValidationError';
  }
}

function asObject(value: unknown, label: string): JsonObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new BoardBundleValidationError(`${label} должен быть JSON-объектом.`);
  }
  return value as JsonObject;
}

function asObjectArray(
  object: JsonObject,
  key: string,
  options: { required?: boolean; warnings?: string[] } = {},
): JsonObject[] {
  const value = object[key];
  if (value === undefined) {
    if (options.required) {
      throw new BoardBundleValidationError(`В payload отсутствует обязательный раздел ${key}.`);
    }
    options.warnings?.push(`Раздел ${key} отсутствует и будет считаться пустым.`);
    return [];
  }
  if (!Array.isArray(value) || value.some((item) => !item || typeof item !== 'object' || Array.isArray(item))) {
    throw new BoardBundleValidationError(`payload.${key} должен быть массивом JSON-объектов.`);
  }
  return value as JsonObject[];
}

function requiredString(object: JsonObject, key: string, label: string): string {
  const value = object[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new BoardBundleValidationError(`${label}.${key} должен быть непустой строкой.`);
  }
  return value;
}

function optionalString(object: JsonObject, key: string): string | undefined {
  const value = object[key];
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed || undefined;
}

function optionalTimestamp(object: JsonObject, key: string, label: string): string | undefined {
  const value = optionalString(object, key);
  if (!value) return undefined;
  if (Number.isNaN(Date.parse(value))) {
    throw new BoardBundleValidationError(`${label}.${key} должен быть корректной датой ISO 8601.`);
  }
  return value;
}

function optionalFiniteNumber(object: JsonObject, key: string, fallback: number, label: string): number {
  const value = object[key];
  if (value === undefined || value === null) return fallback;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new BoardBundleValidationError(`${label}.${key} должен быть конечным числом.`);
  }
  return value;
}

function optionalWipLimit(object: JsonObject, label: string): number | undefined {
  const value = object.wipLimit;
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new BoardBundleValidationError(`${label}.wipLimit должен быть целым неотрицательным числом.`);
  }
  return value;
}

function optionalBoolean(object: JsonObject, key: string, fallback: boolean): boolean {
  return typeof object[key] === 'boolean' ? object[key] : fallback;
}

function isArchived(object: JsonObject): boolean {
  return object.archivedAt !== null && object.archivedAt !== undefined;
}

function ensureUniqueIds(items: Array<{ id: string }>, label: string) {
  const seen = new Set<string>();
  for (const item of items) {
    if (seen.has(item.id)) {
      throw new BoardBundleValidationError(`В разделе ${label} повторяется id ${item.id}.`);
    }
    seen.add(item.id);
  }
}

function ensureReferences(
  source: Array<{ id?: string; ref: string }>,
  targetIds: Set<string>,
  label: string,
) {
  for (const item of source) {
    if (!targetIds.has(item.ref)) {
      const sourceId = item.id ? ` у ${item.id}` : '';
      throw new BoardBundleValidationError(`${label}${sourceId} ссылается на отсутствующий id ${item.ref}.`);
    }
  }
}

function normalizeCardPriority(value: unknown, cardId: string, warnings: string[]): CardPriority {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'string' && ['low', 'medium', 'high', 'urgent'].includes(value)) {
    return value as Exclude<CardPriority, null>;
  }
  warnings.push(`Неизвестный приоритет карточки ${cardId} будет сброшен.`);
  return null;
}

function parseAppearance(rows: JsonObject[], boardId: string, warnings: string[]): UpdateBoardAppearanceRequest | undefined {
  const row = rows.find((item) => item.boardId === boardId);
  if (!row) return undefined;

  const wallpaperKind = optionalString(row, 'wallpaperKind');
  const wallpaperValue = optionalString(row, 'wallpaperValue');
  const allowedWallpaperKinds = new Set(['none', 'accent', 'solid', 'gradient', 'preset', 'image']);
  const allowedDensities = new Set(['comfortable', 'compact']);
  const allowedCardModes = new Set(['compact', 'expanded']);

  let wallpaper: UpdateBoardAppearanceRequest['wallpaper'];
  if (wallpaperKind && allowedWallpaperKinds.has(wallpaperKind)) {
    if (wallpaperKind === 'none' || wallpaperKind === 'accent') {
      wallpaper = { kind: wallpaperKind };
    } else if (wallpaperValue) {
      wallpaper = {
        kind: wallpaperKind as 'solid' | 'gradient' | 'preset' | 'image',
        value: wallpaperValue,
      };
    } else {
      warnings.push('Фон доски пропущен: в bundle нет wallpaperValue.');
    }
  } else if (wallpaperKind) {
    warnings.push(`Неизвестный тип фона ${wallpaperKind} пропущен.`);
  }

  const columnDensity = optionalString(row, 'columnDensity');
  const cardPreviewMode = optionalString(row, 'cardPreviewMode');
  const customProperties = row.customProperties;

  return {
    themePreset: optionalString(row, 'themePreset'),
    wallpaper,
    columnDensity: columnDensity && allowedDensities.has(columnDensity)
      ? columnDensity as 'comfortable' | 'compact'
      : undefined,
    cardPreviewMode: cardPreviewMode && allowedCardModes.has(cardPreviewMode)
      ? cardPreviewMode as 'compact' | 'expanded'
      : undefined,
    showCardDescription: typeof row.showCardDescription === 'boolean' ? row.showCardDescription : undefined,
    showCardDates: typeof row.showCardDates === 'boolean' ? row.showCardDates : undefined,
    showChecklistProgress: typeof row.showChecklistProgress === 'boolean' ? row.showChecklistProgress : undefined,
    customProperties: customProperties && typeof customProperties === 'object' && !Array.isArray(customProperties)
      ? customProperties as Record<string, unknown>
      : undefined,
  };
}

function checkParentCycles(cards: ImportedCardSource[]) {
  const parentByCard = new Map(cards.map((card) => [card.id, card.parentCardId]));
  const visited = new Set<string>();
  const visiting = new Set<string>();

  function visit(cardId: string) {
    if (visited.has(cardId)) return;
    if (visiting.has(cardId)) {
      throw new BoardBundleValidationError(`В иерархии карточек обнаружен цикл около ${cardId}.`);
    }
    visiting.add(cardId);
    const parentId = parentByCard.get(cardId);
    if (parentId) visit(parentId);
    visiting.delete(cardId);
    visited.add(cardId);
  }

  cards.forEach((card) => visit(card.id));
}

function compareManifestCount(
  summary: JsonObject | undefined,
  key: string,
  actual: number,
  warnings: string[],
) {
  if (!summary) return;
  const entityCounts = summary.entityCounts;
  if (!entityCounts || typeof entityCounts !== 'object' || Array.isArray(entityCounts)) return;
  const expected = (entityCounts as JsonObject)[key];
  if (typeof expected === 'number' && expected !== actual) {
    warnings.push(`Manifest сообщает ${expected} ${key}, но в payload найдено ${actual}. Используется фактический payload.`);
  }
}

export function parseBoardBundleText(text: string, fileName = 'board.bundle.json'): BoardBundlePreview {
  if (!text.trim()) {
    throw new BoardBundleValidationError('Выбранный файл пуст.');
  }
  if (new TextEncoder().encode(text).byteLength > MAX_BOARD_BUNDLE_SIZE_BYTES) {
    throw new BoardBundleValidationError('Файл больше 10 МБ. Такой bundle клиент не импортирует.');
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new BoardBundleValidationError('Файл не является корректным JSON.');
  }

  const bundle = asObject(parsed, 'Корень bundle');
  const manifest = asObject(bundle['manifest.json'], 'manifest.json');
  const format = requiredString(manifest, 'format', 'manifest.json');
  const formatVersion = manifest.formatVersion;
  const bundleKind = requiredString(manifest, 'bundleKind', 'manifest.json');
  const scopeKind = requiredString(manifest, 'scopeKind', 'manifest.json');

  if (format !== BOARD_BUNDLE_FORMAT) {
    throw new BoardBundleValidationError(`Формат ${format} не поддерживается. Ожидается ${BOARD_BUNDLE_FORMAT}.`);
  }
  if (formatVersion !== BOARD_BUNDLE_FORMAT_VERSION) {
    throw new BoardBundleValidationError(`Версия bundle ${String(formatVersion)} не поддерживается. Ожидается версия 1.`);
  }
  if (scopeKind !== 'board') {
    throw new BoardBundleValidationError('Сейчас можно импортировать только bundle одной доски.');
  }
  if (bundleKind !== 'portable_export' && bundleKind !== 'backup_snapshot') {
    throw new BoardBundleValidationError(`Тип bundle ${bundleKind} не поддерживается.`);
  }

  const warnings: string[] = [];
  const payload = asObject(bundle.payload, 'payload');
  const boardRows = asObjectArray(payload, 'boards', { required: true });
  const columnRows = asObjectArray(payload, 'columns', { required: true });
  const cardRows = asObjectArray(payload, 'cards', { required: true });
  const labelRows = asObjectArray(payload, 'labels', { warnings });
  const cardLabelRows = asObjectArray(payload, 'cardLabels', { warnings });
  const checklistRows = asObjectArray(payload, 'checklists', { warnings });
  const checklistItemRows = asObjectArray(payload, 'checklistItems', { warnings });
  const commentRows = asObjectArray(payload, 'comments', { warnings });
  const appearanceRows = asObjectArray(payload, 'boardAppearanceSettings', { warnings });
  const activityRows = asObjectArray(payload, 'activityEntries', { warnings });

  const scope = bundle.scope && typeof bundle.scope === 'object' && !Array.isArray(bundle.scope)
    ? bundle.scope as JsonObject
    : {};
  const manifestBoardId = optionalString(manifest, 'boardId') || optionalString(scope, 'boardId');
  const selectedBoardRow = manifestBoardId
    ? boardRows.find((row) => row.id === manifestBoardId)
    : boardRows.length === 1 ? boardRows[0] : undefined;

  if (!selectedBoardRow) {
    throw new BoardBundleValidationError('Не удалось однозначно найти доску из manifest в payload.boards.');
  }
  if (boardRows.length !== 1) {
    warnings.push(`В bundle найдено ${boardRows.length} boards; будет импортирована только доска из manifest.`);
  }

  const boardId = requiredString(selectedBoardRow, 'id', 'payload.boards');
  const board: ImportedBoardSource = {
    id: boardId,
    name: requiredString(selectedBoardRow, 'name', `board ${boardId}`),
    description: optionalString(selectedBoardRow, 'description'),
    isArchived: isArchived(selectedBoardRow),
  };

  const columns = columnRows
    .filter((row) => row.boardId === boardId)
    .map((row, index): ImportedColumnSource => {
      const id = requiredString(row, 'id', 'payload.columns');
      return {
        id,
        name: requiredString(row, 'name', `column ${id}`),
        description: optionalString(row, 'description'),
        position: optionalFiniteNumber(row, 'position', (index + 1) * 1024, `column ${id}`),
        colorToken: optionalString(row, 'colorToken'),
        wipLimit: optionalWipLimit(row, `column ${id}`),
      };
    })
    .sort((left, right) => left.position - right.position);

  const cards = cardRows
    .filter((row) => row.boardId === boardId)
    .map((row, index): ImportedCardSource => {
      const id = requiredString(row, 'id', 'payload.cards');
      return {
        id,
        columnId: requiredString(row, 'columnId', `card ${id}`),
        parentCardId: optionalString(row, 'parentCardId'),
        title: requiredString(row, 'title', `card ${id}`),
        description: optionalString(row, 'description'),
        priority: normalizeCardPriority(row.priority, id, warnings),
        position: optionalFiniteNumber(row, 'position', (index + 1) * 1024, `card ${id}`),
        startAt: optionalTimestamp(row, 'startAt', `card ${id}`),
        dueAt: optionalTimestamp(row, 'dueAt', `card ${id}`),
        isArchived: isArchived(row),
      };
    })
    .sort((left, right) => left.position - right.position);

  const labels = labelRows
    .filter((row) => row.boardId === boardId)
    .map((row): ImportedLabelSource => {
      const id = requiredString(row, 'id', 'payload.labels');
      return {
        id,
        name: requiredString(row, 'name', `label ${id}`),
        color: requiredString(row, 'color', `label ${id}`),
        description: optionalString(row, 'description'),
      };
    });

  const cardLabels = cardLabelRows.map((row): ImportedCardLabelSource => ({
    cardId: requiredString(row, 'cardId', 'payload.cardLabels'),
    labelId: requiredString(row, 'labelId', 'payload.cardLabels'),
  }));

  const checklists = checklistRows
    .map((row, index): ImportedChecklistSource => {
      const id = requiredString(row, 'id', 'payload.checklists');
      return {
        id,
        cardId: requiredString(row, 'cardId', `checklist ${id}`),
        title: requiredString(row, 'title', `checklist ${id}`),
        position: optionalFiniteNumber(row, 'position', (index + 1) * 1024, `checklist ${id}`),
      };
    })
    .sort((left, right) => left.position - right.position);

  const checklistItems = checklistItemRows
    .map((row, index): ImportedChecklistItemSource => {
      const id = requiredString(row, 'id', 'payload.checklistItems');
      return {
        id,
        checklistId: requiredString(row, 'checklistId', `checklist item ${id}`),
        title: requiredString(row, 'title', `checklist item ${id}`),
        isDone: optionalBoolean(row, 'isDone', false),
        position: optionalFiniteNumber(row, 'position', (index + 1) * 1024, `checklist item ${id}`),
      };
    })
    .sort((left, right) => left.position - right.position);

  const comments = commentRows
    .map((row): ImportedCommentSource => {
      const id = requiredString(row, 'id', 'payload.comments');
      return {
        id,
        cardId: requiredString(row, 'cardId', `comment ${id}`),
        body: requiredString(row, 'body', `comment ${id}`),
        createdAt: optionalTimestamp(row, 'createdAt', `comment ${id}`),
      };
    })
    .sort((left, right) => (left.createdAt || '').localeCompare(right.createdAt || ''));

  ensureUniqueIds(columns, 'columns');
  ensureUniqueIds(cards, 'cards');
  ensureUniqueIds(labels, 'labels');
  ensureUniqueIds(checklists, 'checklists');
  ensureUniqueIds(checklistItems, 'checklistItems');
  ensureUniqueIds(comments, 'comments');

  const columnIds = new Set(columns.map((item) => item.id));
  const cardIds = new Set(cards.map((item) => item.id));
  const labelIds = new Set(labels.map((item) => item.id));
  const checklistIds = new Set(checklists.map((item) => item.id));

  ensureReferences(cards.map((card) => ({ id: card.id, ref: card.columnId })), columnIds, 'Карточка');
  ensureReferences(
    cards.filter((card) => card.parentCardId).map((card) => ({ id: card.id, ref: card.parentCardId! })),
    cardIds,
    'Родительская карточка',
  );
  ensureReferences(checklists.map((item) => ({ id: item.id, ref: item.cardId })), cardIds, 'Checklist');
  ensureReferences(checklistItems.map((item) => ({ id: item.id, ref: item.checklistId })), checklistIds, 'Checklist item');
  ensureReferences(comments.map((item) => ({ id: item.id, ref: item.cardId })), cardIds, 'Комментарий');
  ensureReferences(cardLabels.map((item) => ({ ref: item.cardId })), cardIds, 'Связь cardLabels.cardId');
  ensureReferences(cardLabels.map((item) => ({ ref: item.labelId })), labelIds, 'Связь cardLabels.labelId');
  checkParentCycles(cards);

  const manifestSummary = manifest.summary && typeof manifest.summary === 'object' && !Array.isArray(manifest.summary)
    ? manifest.summary as JsonObject
    : undefined;
  compareManifestCount(manifestSummary, 'boards', 1, warnings);
  compareManifestCount(manifestSummary, 'columns', columns.length, warnings);
  compareManifestCount(manifestSummary, 'cards', cards.length, warnings);
  compareManifestCount(manifestSummary, 'comments', comments.length, warnings);
  compareManifestCount(manifestSummary, 'checklists', checklists.length, warnings);

  if (board.isArchived) {
    warnings.push('Исходная доска архивная. Копия будет создана активной.');
  }
  if (activityRows.length) {
    warnings.push(`История из ${activityRows.length} событий не переигрывается; у копии будет новая честная история создания.`);
  }
  if (comments.length) {
    warnings.push('Комментарии сохранят текст, но получат текущего автора и новое время создания.');
  }
  if (optionalBoolean(manifest, 'includesLocalMetadata', false)) {
    warnings.push('Локальные метаданные устройства не импортируются.');
  }
  const includes = bundle.includes && typeof bundle.includes === 'object' && !Array.isArray(bundle.includes)
    ? bundle.includes as JsonObject
    : {};
  if (optionalBoolean(includes, 'attachments', false)) {
    warnings.push('Вложения пока не поддерживаются и будут пропущены.');
  }
  warnings.push('Исходные ID, авторы и временные метки заменяются новыми значениями текущего инстанса.');

  const origin = bundle.origin && typeof bundle.origin === 'object' && !Array.isArray(bundle.origin)
    ? bundle.origin as JsonObject
    : {};

  return {
    fileName,
    bundleKind,
    generatedAt: optionalString(origin, 'generatedAt'),
    board,
    columns,
    cards,
    labels,
    cardLabels,
    checklists,
    checklistItems,
    comments,
    appearance: parseAppearance(appearanceRows, boardId, warnings),
    counts: {
      columns: columns.length,
      cards: cards.length,
      labels: labels.length,
      checklists: checklists.length,
      checklistItems: checklistItems.length,
      comments: comments.length,
    },
    warnings,
  };
}

export async function readBoardBundleFile(file: File): Promise<BoardBundlePreview> {
  if (file.size > MAX_BOARD_BUNDLE_SIZE_BYTES) {
    throw new BoardBundleValidationError('Файл больше 10 МБ. Такой bundle клиент не импортирует.');
  }
  return parseBoardBundleText(await file.text(), file.name);
}

export function chooseImportedBoardName(sourceName: string, existingNames: string[]): string {
  const used = new Set(existingNames.map((name) => name.trim().toLocaleLowerCase()));
  const first = `${sourceName} (импорт)`;
  if (!used.has(first.toLocaleLowerCase())) return first;

  let suffix = 2;
  while (used.has(`${sourceName} (импорт ${suffix})`.toLocaleLowerCase())) {
    suffix += 1;
  }
  return `${sourceName} (импорт ${suffix})`;
}
