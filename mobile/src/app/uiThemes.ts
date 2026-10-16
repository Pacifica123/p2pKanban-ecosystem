// Темы интерфейса приложения (не доски): копия словаря p2p-kanban-ui-themes/1
// из docs/ecosystem/ui-themes.json в корне монорепозитория. Значения меняются
// вместе со словарём: python -B tools/ecosystem/check_ui_themes.py --directions.
export type UiThemeId = 'graphite' | 'lemon' | 'azure' | 'silver';
export type UiScheme = 'light' | 'dark';

export interface UiThemePalette {
  background: string;
  surface: string;
  surfaceMuted: string;
  surfaceRaised: string;
  border: string;
  borderStrong: string;
  text: string;
  textMuted: string;
  accent: string;
  accentStrong: string;
  accentSoft: string;
  accentText: string;
  onAccent: string;
  danger: string;
  dangerText: string;
  success: string;
  successText: string;
  warning: string;
  warningText: string;
  overlay: string;
}

export interface UiThemeDefinition {
  id: UiThemeId;
  label: string;
  description: string;
  scheme: UiScheme;
  colors: UiThemePalette;
}

export const DEFAULT_UI_THEME: UiThemeId = 'graphite';
// Ключ хранилища устройства (AsyncStorage). Не привязан к сеансу: тема
// переживает выход из аккаунта и смену узла.
export const UI_THEME_STORAGE_KEY = 'p2p-kanban.ui-theme';

export const UI_THEMES: UiThemeDefinition[] = [
  {
    id: 'graphite',
    label: 'Графит',
    description: 'Тёмно-серая рабочая',
    scheme: 'dark',
    colors: {
      background: '#1b1e20',
      surface: '#292c30',
      surfaceMuted: '#202326',
      surfaceRaised: '#31363b',
      border: '#3a3f44',
      borderStrong: '#4f555b',
      text: '#fcfcfc',
      textMuted: '#a1a9b1',
      accent: '#3daee9',
      accentStrong: '#2574a9',
      accentSoft: '#1f3a4b',
      accentText: '#3daee9',
      onAccent: '#ffffff',
      danger: '#da4453',
      dangerText: '#f08b95',
      success: '#27ae60',
      successText: '#6fd39a',
      warning: '#f67400',
      warningText: '#fdbc4b',
      overlay: 'rgba(0, 0, 0, 0.6)',
    },
  },
  {
    id: 'lemon',
    label: 'Лимон',
    description: 'Светло-жёлтая flat',
    scheme: 'light',
    colors: {
      background: '#fff7d6',
      surface: '#ffffff',
      surfaceMuted: '#fffbea',
      surfaceRaised: '#ffffff',
      border: '#efe3b5',
      borderStrong: '#d9c47c',
      text: '#333333',
      textMuted: '#6b6250',
      accent: '#ffd667',
      accentStrong: '#f5c400',
      accentSoft: '#fff0b3',
      accentText: '#8a6500',
      onAccent: '#2b2b2b',
      danger: '#d13438',
      dangerText: '#a4262c',
      success: '#107c10',
      successText: '#0b6a0b',
      warning: '#c27c0e',
      warningText: '#8a5300',
      overlay: 'rgba(51, 43, 20, 0.4)',
    },
  },
  {
    id: 'azure',
    label: 'Лазурь',
    description: 'Светло-синяя flat',
    scheme: 'light',
    colors: {
      background: '#e9eff8',
      surface: '#ffffff',
      surfaceMuted: '#f4f7fc',
      surfaceRaised: '#ffffff',
      border: '#d6e0ee',
      borderStrong: '#a9bcd8',
      text: '#252423',
      textMuted: '#605e5c',
      accent: '#2b7cd3',
      accentStrong: '#2b579a',
      accentSoft: '#dce8f7',
      accentText: '#2b579a',
      onAccent: '#ffffff',
      danger: '#d13438',
      dangerText: '#a4262c',
      success: '#107c10',
      successText: '#0b6a0b',
      warning: '#c27c0e',
      warningText: '#8a5300',
      overlay: 'rgba(20, 32, 54, 0.4)',
    },
  },
  {
    id: 'silver',
    label: 'Серебро',
    description: 'Светло-серая flat',
    scheme: 'light',
    colors: {
      background: '#eef0f4',
      surface: '#ffffff',
      surfaceMuted: '#f7f8fa',
      surfaceRaised: '#ffffff',
      border: '#e0e3ea',
      borderStrong: '#bdc3cf',
      text: '#333333',
      textMuted: '#646b77',
      accent: '#00bcf0',
      accentStrong: '#007ba6',
      accentSoft: '#e0f8ff',
      accentText: '#006f92',
      onAccent: '#ffffff',
      danger: '#d13438',
      dangerText: '#a4262c',
      success: '#107c10',
      successText: '#0b6a0b',
      warning: '#c27c0e',
      warningText: '#8a5300',
      overlay: 'rgba(30, 34, 44, 0.4)',
    },
  },
];

export function normalizeUiTheme(value: unknown): UiThemeId {
  return UI_THEMES.some((theme) => theme.id === value) ? value as UiThemeId : DEFAULT_UI_THEME;
}

export function getUiTheme(value: unknown): UiThemeDefinition {
  const id = normalizeUiTheme(value);
  return UI_THEMES.find((theme) => theme.id === id)!;
}

// Смесь двух #rrggbb: доля first от 0 до 1.
export function mixHex(first: string, second: string, share: number) {
  const channel = (hex: string, index: number) => parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16);
  return `#${[0, 1, 2].map((index) => Math.round(
    channel(first, index) * share + channel(second, index) * (1 - share),
  ).toString(16).padStart(2, '0')).join('')}`;
}
