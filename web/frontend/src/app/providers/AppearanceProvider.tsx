import type { PropsWithChildren } from 'react';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useMyAppearanceQuery } from '@/features/appearance/hooks/useAppearance';
import { buildUserAppearancePreview } from '@/shared/appearance/theme';
import type { ResolvedThemeMode } from '@/shared/appearance/theme';
import { UI_THEME_STORAGE_KEY, applyUiTheme, getUiTheme, readStoredUiTheme, writeStoredUiTheme } from '@/shared/appearance/uiThemes';
import type { UiThemeId } from '@/shared/appearance/uiThemes';
import type { UserAppearancePreferences } from '@/shared/types/api';

interface AppearanceContextValue {
  persistedUserAppearance?: UserAppearancePreferences;
  effectiveUserAppearance?: UserAppearancePreferences;
  resolvedTheme: ResolvedThemeMode;
  uiTheme: UiThemeId;
  setUiTheme: (theme: UiThemeId) => void;
  setUserPreview: (patch: Partial<UserAppearancePreferences> | null) => void;
  clearUserPreview: () => void;
}

const AppearanceContext = createContext<AppearanceContextValue | undefined>(undefined);

export function AppearanceProvider({ children }: PropsWithChildren) {
  const myAppearanceQuery = useMyAppearanceQuery();
  const [preview, setPreview] = useState<Partial<UserAppearancePreferences> | null>(null);
  // Тема приложения — настройка устройства: localStorage, на узел не уходит.
  // Поле appTheme на узле остаётся для старых клиентов и здесь не читается.
  const [uiTheme, setUiThemeState] = useState<UiThemeId>(readStoredUiTheme);

  const setUiTheme = useCallback((theme: UiThemeId) => {
    writeStoredUiTheme(theme);
    setUiThemeState(theme);
  }, []);

  useEffect(() => {
    const listener = (event: StorageEvent) => {
      if (event.key === null || event.key === UI_THEME_STORAGE_KEY) setUiThemeState(readStoredUiTheme());
    };
    window.addEventListener('storage', listener);
    return () => window.removeEventListener('storage', listener);
  }, []);

  const effectiveUserAppearance = useMemo(() => {
    if (!myAppearanceQuery.data) return undefined;
    return preview ? buildUserAppearancePreview(myAppearanceQuery.data, preview) : myAppearanceQuery.data;
  }, [myAppearanceQuery.data, preview]);

  const resolvedTheme = getUiTheme(uiTheme).scheme;

  useEffect(() => {
    const root = document.documentElement;
    applyUiTheme(uiTheme, root);

    const appearance = effectiveUserAppearance;
    if (!appearance) return;

    root.dataset.density = appearance.density;
    root.dataset.reduceMotion = String(appearance.reduceMotion);
    root.dataset.checklistItemSubmitMode = appearance.checklistItemSubmitMode;
    root.dataset.cardDetailsMode = appearance.cardDetailsMode;
  }, [effectiveUserAppearance, uiTheme]);

  const value = useMemo<AppearanceContextValue>(
    () => ({
      persistedUserAppearance: myAppearanceQuery.data,
      effectiveUserAppearance,
      resolvedTheme,
      uiTheme,
      setUiTheme,
      setUserPreview: (patch) => setPreview(patch),
      clearUserPreview: () => setPreview(null),
    }),
    [effectiveUserAppearance, myAppearanceQuery.data, resolvedTheme, setUiTheme, uiTheme],
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance() {
  const context = useContext(AppearanceContext);
  if (!context) throw new Error('useAppearance must be used inside AppearanceProvider');
  return context;
}
