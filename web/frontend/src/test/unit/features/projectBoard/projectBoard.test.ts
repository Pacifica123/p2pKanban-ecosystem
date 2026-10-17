import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseBoardBundleText } from '@/features/integrations/lib/boardBundle';
import {
  PROJECT_BOARD_ID, cardChecklists, cardProgress, describeProjectBoard, projectBoardColumns,
  type ProjectBoardNodeSummary, type ProjectBoardSummary,
} from '@/features/projectBoard/lib/projectBoard';

// The board the node builds in (backend/assets/project-board.json) and the
// shared vectors of contracts/project-board/1.
function webDir(): string {
  let dir = resolve(__dirname);
  while (!existsSync(join(dir, 'backend', 'assets', 'project-board.json'))) {
    const parent = dirname(dir);
    if (parent === dir) throw new Error('web/backend/assets/project-board.json not found above the frontend');
    dir = parent;
  }
  return dir;
}
const vendored = () => readFileSync(join(webDir(), 'backend', 'assets', 'project-board.json'), 'utf8');
const vector = (name: string) => JSON.parse(readFileSync(join(webDir(), '..', 'contracts', 'project-board', '1', 'vectors', name), 'utf8'));

function summary(revision: number, sha = 'a'.repeat(64)): ProjectBoardSummary {
  return { protocol: 'p2p-kanban-project-board/1', boardId: PROJECT_BOARD_ID, revision, lastPatchId: `patch-${revision}`, generatedAt: null, sha256: sha, bytes: 10 };
}
function node(partial: Partial<ProjectBoardNodeSummary> & { served: ProjectBoardNodeSummary['served'] }): ProjectBoardNodeSummary {
  return {
    protocol: 'p2p-kanban-project-board/1',
    build: summary(33),
    upstream: { enabled: true, url: 'https://example', checkedAt: '2026-10-17T03:00:00Z', summary: null, error: null },
    ...partial,
  };
}

describe('project board (contracts/project-board/1)', () => {
  it('the vendored board parses as the project board with every column', () => {
    const preview = parseBoardBundleText(vendored());
    expect(preview.board.id).toBe(PROJECT_BOARD_ID);
    const columns = projectBoardColumns(preview);
    expect(columns.map((c) => c.name)).toContain('Готово к патчу');
    expect(columns.reduce((n, c) => n + c.cards.length, 0)).toBe(preview.cards.filter((c) => !c.isArchived).length);
    const positions = columns.map((c) => preview.columns.find((col) => col.id === c.id)!.position);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  it('checklists and progress come from the bundle', () => {
    const preview = parseBoardBundleText(vendored());
    const card = preview.cards.find((c) => cardChecklists(preview, c.id).length)!;
    const progress = cardProgress(preview, card.id)!;
    const items = cardChecklists(preview, card.id).flatMap((c) => c.items);
    expect(progress.total).toBe(items.length);
    expect(progress.done).toBe(items.filter((i) => i.isDone).length);
  });

  it('every vector board that is a project board parses in the web importer', () => {
    for (const c of vector('summary.json').cases) {
      if (c.rejected) continue;
      expect(parseBoardBundleText(c.raw).board.id, c.name).toBe(PROJECT_BOARD_ID);
    }
  });

  it('names the revision, the patch and where the board came from', () => {
    const fromGitHub = describeProjectBoard(node({ served: { source: 'upstream', summary: summary(40) } }));
    expect(fromGitHub.line).toBe('Ревизия 40 · patch-40 · с GitHub (main)');
    expect(fromGitHub.notes[0]).toContain('В сборке узла ревизия 33');

    const offline = describeProjectBoard(node({
      served: { source: 'build', summary: summary(33) },
      upstream: { enabled: true, url: 'https://example', checkedAt: '2026-10-17T03:00:00Z', summary: null, error: 'unreachable: dns' },
    }));
    expect(offline.line).toBe('Ревизия 33 · patch-33 · из сборки узла');
    expect(offline.notes.join(' ')).toContain('GitHub не проверен: unreachable: dns');

    const forked = describeProjectBoard(node({
      served: { source: 'build', summary: summary(33) },
      upstream: { enabled: true, url: 'https://example', checkedAt: '2026-10-17T03:00:00Z', summary: summary(33, 'b'.repeat(64)), error: null },
    }));
    expect(forked.notes.join(' ')).toContain('Две разные доски ревизии 33');
  });
});
