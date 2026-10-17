import selection from '../../../../contracts/project-board/1/vectors/selection.json';
import summaries from '../../../../contracts/project-board/1/vectors/summary.json';
import {
  PROJECT_BOARD_ID,
  ProjectBoardRejected,
  describeSelection,
  projectBoardView,
  selectProjectBoard,
  summarizeProjectBoard,
  type ProjectBoardCandidate,
} from './model';
import { buildRaw } from './buildCopy';

declare const __dirname: string;
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { readFileSync } = require('fs') as { readFileSync: (path: string, encoding: 'utf8') => string };

describe('contracts/project-board/1 vectors', () => {
  it.each(summaries.cases.map((c) => [c.name, c] as const))('summary: %s', (_name, c) => {
    if ('rejected' in c && c.rejected) {
      expect(() => summarizeProjectBoard(c.raw)).toThrow(ProjectBoardRejected);
      try {
        summarizeProjectBoard(c.raw);
      } catch (error) {
        expect((error as ProjectBoardRejected).reason).toBe(c.rejected);
      }
    } else {
      expect(summarizeProjectBoard(c.raw)).toEqual((c as { expected: unknown }).expected);
    }
  });

  it.each(selection.cases.map((c) => [c.name, c] as const))('selection: %s', (_name, c) => {
    expect(selectProjectBoard(c.candidates as ProjectBoardCandidate[])).toEqual(c.expected);
  });
});

describe('the board built into the APK', () => {
  const file = readFileSync(`${__dirname}/../../../assets/project-board.json`, 'utf8');

  it('is restored byte for byte, so its sha256 matches the node', () => {
    expect(buildRaw()).toBe(file);
    expect(summarizeProjectBoard(buildRaw()).boardId).toBe(PROJECT_BOARD_ID);
  });

  it('renders every column and every live card', () => {
    const view = projectBoardView(file);
    const bundle = JSON.parse(file);
    expect(view.columns).toHaveLength(bundle.payload.columns.length);
    const shown = view.columns.reduce((n, c) => n + c.cards.length, 0);
    expect(shown).toBe(bundle.payload.cards.filter((c: { archivedAt: unknown }) => !c.archivedAt).length);
    const withChecklist = view.columns.flatMap((c) => c.cards).find((c) => c.total > 0)!;
    expect(withChecklist.done).toBeLessThanOrEqual(withChecklist.total);
  });

  it('names where the board came from', () => {
    const own = summarizeProjectBoard(buildRaw());
    const chosen = selectProjectBoard([{ source: 'build', summary: own }, { source: 'node', rejected: 'unreachable' }]);
    const text = describeSelection(chosen, { host: '192.168.0.101:8082', state: 'unreachable', sha256: null });
    expect(text.line).toBe(`Ревизия ${own.revision} · ${own.lastPatchId} · из приложения`);
    expect(text.notes[0]).toContain('Узел 192.168.0.101:8082 недоступен');
    const fromNode = describeSelection(
      selectProjectBoard([{ source: 'build', summary: own }, { source: 'node', summary: own }]),
      { host: '192.168.0.101:8082', state: 'ok', sha256: own.sha256 },
    );
    expect(fromNode.line).toBe(`Ревизия ${own.revision} · ${own.lastPatchId} · с узла 192.168.0.101:8082`);
  });
});
