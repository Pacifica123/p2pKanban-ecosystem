import type { PropsWithChildren } from 'react';
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { env } from '@/shared/config/env';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { ensureProjectRoadmapSeed } from '@/features/bootstrap/lib/projectRoadmapSeed';

export function ProjectRoadmapSeedProvider({ children }: PropsWithChildren) {
  const { user, status } = useAuthSession();
  const userId = user?.id || 'anonymous';
  const queryClient = useQueryClient();
  const seedStateRef = useRef<Record<string, 'running' | 'done'>>({});

  useEffect(() => {
    if (!env.enableProjectRoadmapSeed) return;
    if (status !== 'authenticated' || !user?.id) return;
    if (seedStateRef.current[userId]) return;
    seedStateRef.current[userId] = 'running';

    void ensureProjectRoadmapSeed()
      .then(() => {
        seedStateRef.current[userId] = 'done';
        void queryClient.invalidateQueries({
          predicate: ({ queryKey }) => ['workspaces', 'boards', 'columns', 'cards'].includes(String(queryKey[0])),
        });
      })
      .catch((error) => {
        delete seedStateRef.current[userId];
        console.warn('Project roadmap seed skipped:', error);
      });
  }, [queryClient, status, user?.id, userId]);

  return <>{children}</>;
}
