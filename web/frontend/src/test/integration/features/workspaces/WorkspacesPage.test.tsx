vi.mock('@/app/providers/AuthSessionProvider', () => ({ useAuthSession: () => ({ refreshCurrentSession: vi.fn() }) }));
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { WorkspacesPage } from '@/features/workspaces/pages/WorkspacesPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import { makeWorkspace, makeWorkspaceListResponse } from '@/test/factories/workspace';

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('WorkspacesPage', () => {
  it('renders empty state for a clean workspace list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/workspaces')) {
          return jsonResponse({ data: makeWorkspaceListResponse([]) });
        }
        throw new Error(`Unhandled request: ${url}`);
      }),
    );

    renderWithProviders(<WorkspacesPage />);

    expect(await screen.findByText('Пока нет ни одного пространства')).toBeInTheDocument();
    expect(screen.getByText('Новое пространство')).toBeInTheDocument();
  });

  it('submits workspace creation through the real query/mutation layer', async () => {
    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    const createdWorkspace = makeWorkspace({ id: 'workspace-2', name: 'Roadmap' });

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method || 'GET';
        const body = typeof init?.body === 'string' ? init.body : null;
        requests.push({ url, method, body });

        if (url.endsWith('/workspaces') && method === 'GET') {
          return jsonResponse({ data: makeWorkspaceListResponse([]) });
        }

        if (url.endsWith('/workspaces') && method === 'POST') {
          return jsonResponse({ data: createdWorkspace }, 201);
        }

        throw new Error(`Unhandled request: ${method} ${url}`);
      }),
    );

    renderWithProviders(<WorkspacesPage />);

    await screen.findByText('Пока нет ни одного пространства');

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Название'), 'Roadmap');
    await user.type(screen.getByLabelText('Описание'), 'Test workspace');
    await user.click(screen.getByRole('button', { name: 'Создать пространство' }));

    await waitFor(() => {
      expect(requests.some((request) => request.method === 'POST' && request.url.endsWith('/workspaces'))).toBe(true);
    });

    const createRequest = requests.find((request) => request.method === 'POST' && request.url.endsWith('/workspaces'));
    expect(createRequest?.body).toContain('Roadmap');
    expect(createRequest?.body).toContain('Test workspace');
  });
});
