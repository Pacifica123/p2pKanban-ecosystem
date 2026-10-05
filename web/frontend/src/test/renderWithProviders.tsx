import type { PropsWithChildren, ReactElement } from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter, type MemoryRouterProps } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

interface RenderWithProvidersOptions {
  router?: Pick<MemoryRouterProps, 'initialEntries' | 'initialIndex'>;
}

function Wrapper({ children, router }: PropsWithChildren<{ router?: RenderWithProvidersOptions['router'] }>) {
  const client = createTestQueryClient();

  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={router?.initialEntries} initialIndex={router?.initialIndex}>
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  );
}

export function renderWithProviders(ui: ReactElement, options?: RenderWithProvidersOptions) {
  return render(ui, {
    wrapper: ({ children }) => <Wrapper router={options?.router}>{children}</Wrapper>,
  });
}
