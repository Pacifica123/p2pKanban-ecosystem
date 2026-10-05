import { createContext, type PropsWithChildren, useContext } from 'react';

import type { AppColors } from './theme';

const ColorOverrideContext = createContext<Partial<AppColors> | null>(null);

export function ColorOverrideProvider({
  colors,
  children,
}: PropsWithChildren<{ colors: Partial<AppColors> }>) {
  return (
    <ColorOverrideContext.Provider value={colors}>
      {children}
    </ColorOverrideContext.Provider>
  );
}

export function useColorOverride() {
  return useContext(ColorOverrideContext);
}
