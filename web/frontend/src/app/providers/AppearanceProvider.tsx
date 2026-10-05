import type { PropsWithChildren } from 'react';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useMyAppearanceQuery } from '@/features/appearance/hooks/useAppearance';
import { buildUserAppearancePreview, resolveSystemTheme } from '@/shared/appearance/theme';
import type { ResolvedThemeMode } from '@/shared/appearance/theme';
import type { UserAppearancePreferences } from '@/shared/types/api';

interface AppearanceContextValue {
  persistedUserAppearance?: UserAppearancePreferences;
  effectiveUserAppearance?: UserAppearancePreferences;
  resolvedTheme: ResolvedThemeMode;
  setUserPreview: (patch: Partial<UserAppearancePreferences> | null) => void;
  clearUserPreview: () => void;
}

const AppearanceContext = createContext<AppearanceContextValue | undefined>(undefined);

function getSystemPrefersDark() {
  if (typeof window === 'undefined') return true;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function AppearanceProvider({ children }: PropsWithChildren) {
  const myAppearanceQuery = useMyAppearanceQuery();
  const [systemPrefersDark, setSystemPrefersDark] = useState(getSystemPrefersDark);
  const [preview, setPreview] = useState<Partial<UserAppearancePreferences> | null>(null);

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = (event: MediaQueryListEvent) => setSystemPrefersDark(event.matches);
    if (media.addEventListener) {
      media.addEventListener('change', listener);
      return () => media.removeEventListener('change', listener);
    }
    media.addListener(listener);
    return () => media.removeListener(listener);
  }, []);

  const effectiveUserAppearance = useMemo(() => {
    if (!myAppearanceQuery.data) return undefined;
    return preview ? buildUserAppearancePreview(myAppearanceQuery.data, preview) : myAppearanceQuery.data;
  }, [myAppearanceQuery.data, preview]);

  const resolvedTheme = useMemo<ResolvedThemeMode>(() => {
    return resolveSystemTheme(effectiveUserAppearance?.appTheme || 'system', systemPrefersDark);
  }, [effectiveUserAppearance?.appTheme, systemPrefersDark]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;

    const appearance = effectiveUserAppearance;
    if (!appearance) return;

    root.dataset.density = appearance.density;
    root.dataset.reduceMotion = String(appearance.reduceMotion);
    root.dataset.checklistItemSubmitMode = appearance.checklistItemSubmitMode;
    root.dataset.cardDetailsMode = appearance.cardDetailsMode;
  }, [effectiveUserAppearance, resolvedTheme]);

  const value = useMemo<AppearanceContextValue>(
    () => ({
      persistedUserAppearance: myAppearanceQuery.data,
      effectiveUserAppearance,
      resolvedTheme,
      setUserPreview: (patch) => setPreview(patch),
      clearUserPreview: () => setPreview(null),
    }),
    [effectiveUserAppearance, myAppearanceQuery.data, resolvedTheme],
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance() {
  const context = useContext(AppearanceContext);
  if (!context) throw new Error('useAppearance must be used inside AppearanceProvider');
  return context;
}
