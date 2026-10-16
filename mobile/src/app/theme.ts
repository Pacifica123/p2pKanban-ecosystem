import { useUiTheme } from './UiThemeProvider';
import { useColorOverride } from './ColorOverrideProvider';
import { getUiTheme, mixHex } from './uiThemes';
import type { UiScheme, UiThemeId } from './uiThemes';

export interface AppColors {
  background: string;
  surface: string;
  surfaceMuted: string;
  surfaceRaised: string;
  border: string;
  text: string;
  muted: string;
  /** Заливка главной кнопки, отметки, индикатора. Текст на ней — onAccent. */
  accent: string;
  /** Ссылки, выбранный пункт, индикатор загрузки на surface. */
  accentText: string;
  onAccent: string;
  accentSoft: string;
  danger: string;
  dangerSoft: string;
  success: string;
  warning: string;
  overlay: string;
}

export function appColorsFor(themeId: UiThemeId): AppColors {
  const { colors } = getUiTheme(themeId);
  return {
    background: colors.background,
    surface: colors.surface,
    surfaceMuted: colors.surfaceMuted,
    surfaceRaised: colors.surfaceRaised,
    border: colors.border,
    text: colors.text,
    muted: colors.textMuted,
    accent: colors.accentStrong,
    accentText: colors.accentText,
    onAccent: colors.onAccent,
    accentSoft: colors.accentSoft,
    danger: colors.dangerText,
    dangerSoft: mixHex(colors.danger, colors.surface, 0.16),
    success: colors.successText,
    warning: colors.warningText,
    overlay: colors.overlay,
  };
}

/** Цвета темы приложения в форме палитры доски (для пресета «System»). */
export function boardPaletteFromApp(colors: AppColors) {
  return {
    background: colors.background,
    column: colors.surfaceMuted,
    card: colors.surfaceRaised,
    text: colors.text,
    muted: colors.muted,
    border: colors.border,
    accent: colors.accentText,
  };
}

export function useAppColors() {
  const base = appColorsFor(useUiTheme().theme);
  const override = useColorOverride();
  return override ? { ...base, ...override } : base;
}

export function useResolvedTheme(): UiScheme {
  return getUiTheme(useUiTheme().theme).scheme;
}

export const spacing = {
  xs: 6,
  sm: 10,
  md: 16,
  lg: 22,
  xl: 30,
};

export const radius = {
  sm: 7,
  md: 10,
  lg: 14,
};
