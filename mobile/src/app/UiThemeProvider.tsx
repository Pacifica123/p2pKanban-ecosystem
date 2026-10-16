import AsyncStorage from '@react-native-async-storage/async-storage';
import type { PropsWithChildren } from 'react';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { DEFAULT_UI_THEME, UI_THEME_STORAGE_KEY, normalizeUiTheme } from './uiThemes';
import type { UiThemeId } from './uiThemes';

interface UiThemeContextValue {
  theme: UiThemeId;
  setTheme: (theme: UiThemeId) => void;
}

const UiThemeContext = createContext<UiThemeContextValue>({
  theme: DEFAULT_UI_THEME,
  setTheme: () => undefined,
});

// Тема приложения — настройка устройства: хранилище телефона, на узел не
// уходит и не ждёт сети. Поле appTheme на узле mobile больше не читает.
export function UiThemeProvider({ children }: PropsWithChildren) {
  const [theme, setThemeState] = useState<UiThemeId>(DEFAULT_UI_THEME);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void AsyncStorage.getItem(UI_THEME_STORAGE_KEY)
      .then((stored) => {
        if (!cancelled && !touched) setThemeState(normalizeUiTheme(stored));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [touched]);

  const setTheme = useCallback((next: UiThemeId) => {
    setTouched(true);
    setThemeState(next);
    void AsyncStorage.setItem(UI_THEME_STORAGE_KEY, next).catch(() => undefined);
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [setTheme, theme]);
  return <UiThemeContext.Provider value={value}>{children}</UiThemeContext.Provider>;
}

export function useUiTheme() {
  return useContext(UiThemeContext);
}
