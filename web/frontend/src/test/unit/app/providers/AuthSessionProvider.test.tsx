import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthSessionProvider, useAuthSession } from '@/app/providers/AuthSessionProvider';
import type { AuthSuccessResponse } from '@/shared/types/api';

const authApi = vi.hoisted(() => ({
  importAccountFromNode: vi.fn(),
  refreshSession: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  signOutAll: vi.fn(),
  signUp: vi.fn(),
}));

vi.mock('@/features/auth/api/auth', () => authApi);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });

  return { promise, resolve, reject };
}

function authResponse(email: string): AuthSuccessResponse {
  return {
    authenticated: true,
    mode: 'password',
    accessToken: 'access-token',
    accessTokenExpiresAt: '2026-05-26T12:00:00Z',
    sessionId: 'session-1',
    deviceId: 'device-1',
    user: {
      id: 'user-1',
      email,
      displayName: 'Race Smoke',
    },
  };
}

function Wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={client}>
      <AuthSessionProvider>{children}</AuthSessionProvider>
    </QueryClientProvider>
  );
}

function Harness() {
  const { status, user, signInFromAnotherNode, signUpWithPassword } = useAuthSession();

  return (
    <div>
      <p data-testid="status">{status}</p>
      <p data-testid="email">{user?.email ?? 'none'}</p>
      <button
        type="button"
        onClick={() => {
          void signUpWithPassword({
            email: 'race-smoke@local.test',
            password: 'password123',
            displayName: 'Race Smoke',
          });
        }}
      >
        Sign up
      </button>
      <button
        type="button"
        onClick={() => {
          void signInFromAnotherNode({
            sourceUrl: 'http://192.168.1.42:8080',
            email: 'linked@local.test',
            password: 'password123',
          });
        }}
      >
        Link node
      </button>
    </div>
  );
}

describe('AuthSessionProvider', () => {
  beforeEach(() => {
    authApi.importAccountFromNode.mockReset();
    authApi.refreshSession.mockReset();
    authApi.signIn.mockReset();
    authApi.signOut.mockReset();
    authApi.signOutAll.mockReset();
    authApi.signUp.mockReset();
  });

  it('applies an imported web-node identity as the active session', async () => {
    authApi.refreshSession.mockRejectedValue(new Error('clean node'));
    authApi.importAccountFromNode.mockResolvedValue(authResponse('linked@local.test'));

    render(<Harness />, { wrapper: Wrapper });
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'));
    fireEvent.click(screen.getByRole('button', { name: 'Link node' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('email')).toHaveTextContent('linked@local.test');
    expect(authApi.importAccountFromNode).toHaveBeenCalledWith({
      sourceUrl: 'http://192.168.1.42:8080',
      email: 'linked@local.test',
      password: 'password123',
    });
  });

  it('does not let a stale bootstrap refresh failure clear a successful explicit sign-up', async () => {
    const bootstrapRefresh = deferred<AuthSuccessResponse>();
    authApi.refreshSession.mockReturnValue(bootstrapRefresh.promise);
    authApi.signUp.mockResolvedValue(authResponse('race-smoke@local.test'));

    render(<Harness />, { wrapper: Wrapper });

    expect(screen.getByTestId('status')).toHaveTextContent('loading');
    fireEvent.click(screen.getByRole('button', { name: 'Sign up' }));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('email')).toHaveTextContent('race-smoke@local.test');

    bootstrapRefresh.reject(new Error('refresh cookie was absent before sign-up completed'));

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('email')).toHaveTextContent('race-smoke@local.test');
  });
});
