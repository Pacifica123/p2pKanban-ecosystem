import type { PropsWithChildren } from 'react';
import { QueryProvider } from '@/app/providers/QueryProvider';
import { AuthSessionProvider } from '@/app/providers/AuthSessionProvider';
import { AppearanceProvider } from '@/app/providers/AppearanceProvider';
import { ProjectRoadmapSeedProvider } from '@/features/bootstrap/providers/ProjectRoadmapSeedProvider';
import { LocalReminderProvider } from '@/features/reminders/providers/LocalReminderProvider';

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <QueryProvider>
      <AuthSessionProvider>
        <ProjectRoadmapSeedProvider>
          <AppearanceProvider>
            <LocalReminderProvider>{children}</LocalReminderProvider>
          </AppearanceProvider>
        </ProjectRoadmapSeedProvider>
      </AuthSessionProvider>
    </QueryProvider>
  );
}
