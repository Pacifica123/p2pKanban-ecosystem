import { createContext, useContext, type PropsWithChildren } from 'react';
import type { LocalFirstBoardRuntime } from '@/features/localFirst/types';

const LocalFirstBoardContext = createContext<LocalFirstBoardRuntime | null>(null);

interface LocalFirstBoardProviderProps extends PropsWithChildren {
  value: LocalFirstBoardRuntime;
}

export function LocalFirstBoardProvider({ value, children }: LocalFirstBoardProviderProps) {
  return <LocalFirstBoardContext.Provider value={value}>{children}</LocalFirstBoardContext.Provider>;
}

export function useOptionalLocalFirstBoard() {
  return useContext(LocalFirstBoardContext);
}

export function useLocalFirstBoard() {
  const runtime = useContext(LocalFirstBoardContext);
  if (!runtime) {
    throw new Error('useLocalFirstBoard must be used inside LocalFirstBoardProvider.');
  }
  return runtime;
}
