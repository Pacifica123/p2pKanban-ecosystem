import type { PropsWithChildren } from 'react';
import { QueryProvider } from '@/app/providers/QueryProvider';
import { AuthSessionProvider } from '@/app/providers/AuthSessionProvider';
import { AppearanceProvider } from '@/app/providers/AppearanceProvider';
import { LocalReminderProvider } from '@/features/reminders/providers/LocalReminderProvider';

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <QueryProvider>
      <AuthSessionProvider>
        <AppearanceProvider>
          <LocalReminderProvider>{children}</LocalReminderProvider>
        </AppearanceProvider>
      </AuthSessionProvider>
    </QueryProvider>
  );
}
