// p2p-kanban-project-board/1 (contracts/project-board/1/SPEC.md): what is the
// project board and which candidate to show. The shared vectors in contracts/
// are the source of truth (model.test.ts next to this file).
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';

export const PROJECT_BOARD_PROTOCOL = 'p2p-kanban-project-board/1';
export const PROJECT_BOARD_ID = '01a10d38-f902-7665-8612-3e74278ceafa';
export const PROJECT_WORKSPACE_ID = '01a10d38-f901-746d-92f7-10598bb1cc42';
export const PROJECT_BOARD_MAX_BYTES = 10 * 1024 * 1024;

export type ProjectBoardSource = 'build' | 'cache' | 'node' | 'upstream';
export type ProjectBoardRejection =
  | 'not-json' | 'too-large' | 'wrong-format' | 'foreign-board' | 'no-revision' | 'unreachable' | 'http-error';

export interface ProjectBoardSummary {
  protocol: typeof PROJECT_BOARD_PROTOCOL;
  boardId: string;
  revision: number;
  lastPatchId: string;
  generatedAt: string | null;
  sha256: string;
  bytes: number;
}

export type ProjectBoardCandidate =
  | { source: ProjectBoardSource; summary: ProjectBoardSummary }
  | { source: ProjectBoardSource; rejected: ProjectBoardRejection };

export interface ProjectBoardSelection {
  protocol: typeof PROJECT_BOARD_PROTOCOL;
  chosen: ProjectBoardSource | null;
  revision: number | null;
  lastPatchId: string | null;
  sha256: string | null;
  conflict: boolean;
  behind: Array<{ source: ProjectBoardSource; revision: number }>;
  rejected: Array<{ source: ProjectBoardSource; reason: ProjectBoardRejection }>;
}

export class ProjectBoardRejected extends Error {
  constructor(readonly reason: ProjectBoardRejection) {
    super(reason);
    this.name = 'ProjectBoardRejected';
  }
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value);

/** UTF-8 text of a portable board → its summary, or ProjectBoardRejected with the SPEC code. */
export function summarizeProjectBoard(raw: string): ProjectBoardSummary {
  const bytes = new TextEncoder().encode(raw);
  if (bytes.length > PROJECT_BOARD_MAX_BYTES) throw new ProjectBoardRejected('too-large');
  let bundle: unknown;
  try {
    bundle = JSON.parse(raw);
  } catch {
    throw new ProjectBoardRejected('not-json');
  }
  if (!isObject(bundle)) throw new ProjectBoardRejected('not-json');
  const manifest = bundle['manifest.json'];
  const origin = bundle.origin;
  if (!isObject(manifest) || manifest.format !== 'p2p_planner_bundle' || manifest.formatVersion !== 1
    || manifest.bundleKind !== 'portable_export' || manifest.scopeKind !== 'board') {
    throw new ProjectBoardRejected('wrong-format');
  }
  if (manifest.boardId !== PROJECT_BOARD_ID || manifest.workspaceId !== PROJECT_WORKSPACE_ID
    || !isObject(origin) || origin.selfHosted !== true) {
    throw new ProjectBoardRejected('foreign-board');
  }
  const revision = origin.boardRevision;
  const patch = origin.lastPatchId;
  if (typeof revision !== 'number' || !Number.isInteger(revision) || revision < 1
    || typeof patch !== 'string' || !patch.trim()) {
    throw new ProjectBoardRejected('no-revision');
  }
  return {
    protocol: PROJECT_BOARD_PROTOCOL,
    boardId: PROJECT_BOARD_ID,
    revision,
    lastPatchId: patch,
    generatedAt: typeof origin.generatedAt === 'string' ? origin.generatedAt : null,
    sha256: bytesToHex(sha256(bytes)),
    bytes: bytes.length,
  };
}

/** Higher revision wins; same revision and other bytes — lower sha256 and conflict; same bytes — first listed. */
export function selectProjectBoard(candidates: ProjectBoardCandidate[]): ProjectBoardSelection {
  const valid = candidates.filter((c): c is Extract<ProjectBoardCandidate, { summary: ProjectBoardSummary }> => 'summary' in c);
  const rejected = candidates
    .filter((c): c is Extract<ProjectBoardCandidate, { rejected: ProjectBoardRejection }> => 'rejected' in c)
    .map((c) => ({ source: c.source, reason: c.rejected }));
  if (!valid.length) {
    return { protocol: PROJECT_BOARD_PROTOCOL, chosen: null, revision: null, lastPatchId: null, sha256: null, conflict: false, behind: [], rejected };
  }
  const top = Math.max(...valid.map((c) => c.summary.revision));
  const leaders = valid.filter((c) => c.summary.revision === top);
  const hashes = [...new Set(leaders.map((c) => c.summary.sha256))].sort();
  const winner = leaders.find((c) => c.summary.sha256 === hashes[0]) ?? leaders[0]!;
  return {
    protocol: PROJECT_BOARD_PROTOCOL,
    chosen: winner.source,
    revision: top,
    lastPatchId: winner.summary.lastPatchId,
    sha256: winner.summary.sha256,
    conflict: hashes.length > 1,
    behind: valid.filter((c) => c.summary.revision < top).map((c) => ({ source: c.source, revision: c.summary.revision })),
    rejected,
  };
}

export interface ProjectBoardView {
  name: string;
  columns: Array<{ id: string; name: string; cards: ProjectBoardCardView[] }>;
}

export interface ProjectBoardCardView {
  id: string;
  title: string;
  description: string;
  priority: string | null;
  labels: Array<{ name: string; color: string }>;
  checklists: Array<{ id: string; title: string; items: Array<{ id: string; title: string; isDone: boolean }> }>;
  comments: Array<{ id: string; body: string; createdAt: string | null }>;
  done: number;
  total: number;
}

const rows = (payload: Json, key: string) => (Array.isArray(payload[key]) ? payload[key] as Json[] : []).filter(isObject);
const str = (value: unknown) => (typeof value === 'string' ? value : '');
const pos = (value: unknown) => (typeof value === 'number' ? value : 0);

/** Read-only view of an accepted project board: columns by position, archived cards left out. */
export function projectBoardView(raw: string): ProjectBoardView {
  const bundle = JSON.parse(raw) as Json;
  const payload = isObject(bundle.payload) ? bundle.payload : {};
  const labels = new Map(rows(payload, 'labels').map((l) => [str(l.id), { name: str(l.name), color: str(l.color) || '#888888' }]));
  const labelsByCard = new Map<string, Array<{ name: string; color: string }>>();
  for (const edge of rows(payload, 'cardLabels')) {
    const label = labels.get(str(edge.labelId));
    if (!label) continue;
    labelsByCard.set(str(edge.cardId), [...(labelsByCard.get(str(edge.cardId)) ?? []), label]);
  }
  const items = rows(payload, 'checklistItems');
  const checklistsByCard = new Map<string, ProjectBoardCardView['checklists']>();
  for (const checklist of [...rows(payload, 'checklists')].sort((a, b) => pos(a.position) - pos(b.position))) {
    const entry = {
      id: str(checklist.id),
      title: str(checklist.title),
      items: items.filter((i) => i.checklistId === checklist.id)
        .sort((a, b) => pos(a.position) - pos(b.position))
        .map((i) => ({ id: str(i.id), title: str(i.title), isDone: i.isDone === true })),
    };
    checklistsByCard.set(str(checklist.cardId), [...(checklistsByCard.get(str(checklist.cardId)) ?? []), entry]);
  }
  const commentsByCard = new Map<string, ProjectBoardCardView['comments']>();
  for (const comment of rows(payload, 'comments')) {
    const list = commentsByCard.get(str(comment.cardId)) ?? [];
    list.push({ id: str(comment.id), body: str(comment.body), createdAt: str(comment.createdAt) || null });
    commentsByCard.set(str(comment.cardId), list);
  }
  const cards = rows(payload, 'cards').filter((c) => !c.archivedAt && c.isArchived !== true);
  const columns = [...rows(payload, 'columns')].sort((a, b) => pos(a.position) - pos(b.position)).map((column) => ({
    id: str(column.id),
    name: str(column.name),
    cards: cards.filter((c) => c.columnId === column.id).sort((a, b) => pos(a.position) - pos(b.position)).map((card) => {
      const checklists = checklistsByCard.get(str(card.id)) ?? [];
      const all = checklists.flatMap((c) => c.items);
      return {
        id: str(card.id),
        title: str(card.title),
        description: str(card.description),
        priority: typeof card.priority === 'string' ? card.priority : null,
        labels: labelsByCard.get(str(card.id)) ?? [],
        checklists,
        comments: (commentsByCard.get(str(card.id)) ?? []).sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt))),
        done: all.filter((i) => i.isDone).length,
        total: all.length,
      };
    }),
  }));
  const board = rows(payload, 'boards')[0];
  return { name: board ? str(board.name) : 'Доска проекта', columns };
}

const SOURCE_TEXT: Record<ProjectBoardSource, string> = {
  build: 'из приложения',
  cache: 'сохранённая с узла',
  node: 'с узла',
  upstream: 'с GitHub',
};

/** «Ревизия 34 · <patch> · с узла 192.168.0.101:8082» and the notes under it. */
export function describeSelection(
  selection: ProjectBoardSelection,
  node: { host: string | null; state: 'ok' | 'unreachable' | 'http-error' | 'no-node'; sha256: string | null },
): { line: string; notes: string[] } {
  if (!selection.chosen || selection.revision === null) return { line: 'Доска проекта недоступна', notes: [] };
  const fromNode = node.state === 'ok' && node.sha256 === selection.sha256;
  const source = fromNode ? `с узла ${node.host ?? ''}`.trim() : SOURCE_TEXT[selection.chosen];
  const notes: string[] = [];
  if (node.state === 'unreachable') notes.push(`Узел ${node.host ?? ''} недоступен: показана последняя известная ревизия.`.replace('  ', ' '));
  if (node.state === 'http-error') notes.push('Узел не отдал доску проекта: возможно, он старее этого приложения.');
  for (const item of selection.behind) {
    if (item.source === 'build') notes.push(`В этой сборке приложения ревизия ${item.revision}.`);
    if (item.source === 'node') notes.push(`На узле ревизия ${item.revision}: узел старее.`);
  }
  if (selection.conflict) notes.push(`Две разные доски ревизии ${selection.revision}: показана одна из них по правилу контракта.`);
  return { line: `Ревизия ${selection.revision} · ${selection.lastPatchId} · ${source}`, notes };
}
