import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { ProjectBoardPage } from '@/features/projectBoard/pages/ProjectBoardPage';
import { renderWithProviders } from '@/test/renderWithProviders';

const board = readFileSync(resolve(__dirname, '../../../../../../backend/assets/project-board.json'), 'utf8');
const origin = JSON.parse(board).origin as { boardRevision: number; lastPatchId: string };
const summary = {
  protocol: 'p2p-kanban-project-board/1', boardId: '01a10d38-f902-7665-8612-3e74278ceafa',
  revision: origin.boardRevision, lastPatchId: origin.lastPatchId, generatedAt: null, sha256: 'a'.repeat(64), bytes: board.length,
};

describe('ProjectBoardPage', () => {
  it('shows the project board read-only with its revision and source', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push(`${init?.method ?? 'GET'} ${url}`);
      if (url.endsWith('/project-board/summary')) {
        return new Response(JSON.stringify({ data: {
          protocol: 'p2p-kanban-project-board/1', served: { source: 'build', summary }, build: summary,
          upstream: { enabled: true, url: 'https://raw.githubusercontent.com/x', checkedAt: null, summary: null, error: null },
        } }), { headers: { 'Content-Type': 'application/json' } });
      }
      if (url.endsWith('/project-board')) return new Response(board, { headers: { 'Content-Type': 'application/json' } });
      throw new Error(`Unhandled request: ${url}`);
    }));

    renderWithProviders(<ProjectBoardPage />);

    expect(await screen.findByTestId('project-board-revision')).toHaveTextContent(
      `Ревизия ${origin.boardRevision} · ${origin.lastPatchId} · из сборки узла`,
    );
    expect(screen.getByText(/Только чтение/)).toBeInTheDocument();
    expect(screen.getAllByTestId('project-board-column').length).toBe(8);
    expect(screen.queryByRole('button', { name: /Удалить|Переименовать|Создать/ })).toBeNull();

    const card = screen.getAllByTestId('project-board-card')[0];
    await userEvent.click(card);
    const details = await screen.findByTestId('project-board-card-details');
    expect(within(details).getByText(/только чтение/)).toBeInTheDocument();
    expect(requests.every((r) => r.startsWith('GET '))).toBe(true);
  });
});
