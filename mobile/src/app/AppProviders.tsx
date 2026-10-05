import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { useState } from 'react';
import { SafeAreaProvider, initialWindowMetrics } from 'react-native-safe-area-context';

import { AuthProvider } from '../features/auth/AuthProvider';
import { AppearanceProvider } from '../features/appearance/AppearanceProvider';
import { ConnectionProvider } from '../features/connection/ConnectionProvider';
import { ReminderProvider } from '../features/reminders/ReminderProvider';
import { NetworkProvider } from './NetworkProvider';

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 20_000,
        gcTime: 10 * 60_000,
      },
      mutations: {
        retry: 0,
      },
    },
  }));

  return (
    <SafeAreaProvider initialMetrics={initialWindowMetrics}>
      <QueryClientProvider client={queryClient}>
        <ConnectionProvider>
          <NetworkProvider>
            <AuthProvider>
              <AppearanceProvider>
                <ReminderProvider>{children}</ReminderProvider>
              </AppearanceProvider>
            </AuthProvider>
          </NetworkProvider>
        </ConnectionProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
