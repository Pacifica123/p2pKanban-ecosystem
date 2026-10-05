import type { PropsWithChildren } from 'react';
import { useMemo } from 'react';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';

interface DevSessionContextValue {
  userId: string;
  setUserId: (_next: string) => void;
}

export function resolveDevUserId() {
  return '';
}

export function DevSessionProvider({ children }: PropsWithChildren) {
  return <>{children}</>;
}

export function useDevSession(): DevSessionContextValue {
  const { user } = useAuthSession();
  return useMemo(
    () => ({
      userId: user?.id || 'anonymous',
      setUserId: () => {
        // compatibility shim kept during auth transition
      },
    }),
    [user?.id],
  );
}
