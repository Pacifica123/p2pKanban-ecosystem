import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthPage } from '@/features/auth/pages/AuthPage';

const auth = vi.hoisted(() => ({
  signInFromAnotherNode: vi.fn(),
  signInWithPassword: vi.fn(),
  signUpWithPassword: vi.fn(),
}));

vi.mock('@/app/providers/AuthSessionProvider', () => ({
  useAuthSession: () => ({
    status: 'anonymous',
    ...auth,
  }),
}));

describe('AuthPage web-node link', () => {
  function renderPage() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AuthPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  beforeEach(() => {
    auth.signInFromAnotherNode.mockReset();
    auth.signInWithPassword.mockReset();
    auth.signUpWithPassword.mockReset();
    auth.signInFromAnotherNode.mockResolvedValue(undefined);
  });

  it('submits source node credentials through the explicit link mode', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Подключить с другого узла' }));
    fireEvent.change(screen.getByTestId('auth-source-url'), {
      target: { value: 'http://192.168.1.42:8080/' },
    });
    fireEvent.change(screen.getByTestId('auth-email'), {
      target: { value: 'owner@example.org' },
    });
    fireEvent.change(screen.getByTestId('auth-password'), {
      target: { value: 'password123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Подключить и перенести доски' }));

    await waitFor(() =>
      expect(auth.signInFromAnotherNode).toHaveBeenCalledWith({
        sourceUrl: 'http://192.168.1.42:8080/',
        email: 'owner@example.org',
        password: 'password123',
      }),
    );
  });

  it('warns that registration creates a deployment-local identity', () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Создать отдельный аккаунт' }));
    expect(
      screen.getByText(/Совпадающий email на другом узле не связывает аккаунты/),
    ).toBeInTheDocument();
  });
});
