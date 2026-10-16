import type { ResolvedThemeMode } from '@/shared/appearance/theme';

// Темы интерфейса приложения (не доски): словарь p2p-kanban-ui-themes/1,
// docs/ecosystem/ui-themes.md. Цвета лежат в app/styles/themes.css; здесь
// только список для выбора и образцы для превью.
export type UiThemeId = 'graphite' | 'lemon' | 'azure' | 'silver';

export interface UiThemeDefinition {
  id: UiThemeId;
  label: string;
  description: string;
  scheme: ResolvedThemeMode;
  swatches: { background: string; surface: string; accent: string; text: string };
}

export const DEFAULT_UI_THEME: UiThemeId = 'graphite';
export const UI_THEME_STORAGE_KEY = 'p2p-kanban.ui-theme';

export const UI_THEMES: UiThemeDefinition[] = [
  {
    id: 'graphite',
    label: 'Графит',
    description: 'Тёмно-серая рабочая',
    scheme: 'dark',
    swatches: { background: '#1b1e20', surface: '#202326', accent: '#3daee9', text: '#fcfcfc' },
  },
  {
    id: 'lemon',
    label: 'Лимон',
    description: 'Светло-жёлтая flat',
    scheme: 'light',
    swatches: { background: '#fff7d6', surface: '#fffbea', accent: '#f5c400', text: '#333333' },
  },
  {
    id: 'azure',
    label: 'Лазурь',
    description: 'Светло-синяя flat',
    scheme: 'light',
    swatches: { background: '#e9eff8', surface: '#f4f7fc', accent: '#2b7cd3', text: '#252423' },
  },
  {
    id: 'silver',
    label: 'Серебро',
    description: 'Светло-серая flat',
    scheme: 'light',
    swatches: { background: '#eef0f4', surface: '#f7f8fa', accent: '#00bcf0', text: '#333333' },
  },
];

export function normalizeUiTheme(value: unknown): UiThemeId {
  return UI_THEMES.some((theme) => theme.id === value) ? value as UiThemeId : DEFAULT_UI_THEME;
}

export function getUiTheme(id: unknown): UiThemeDefinition {
  const normalized = normalizeUiTheme(id);
  return UI_THEMES.find((theme) => theme.id === normalized)!;
}

export function readStoredUiTheme(): UiThemeId {
  try {
    return normalizeUiTheme(window.localStorage.getItem(UI_THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_UI_THEME;
  }
}

export function writeStoredUiTheme(id: UiThemeId) {
  try {
    window.localStorage.setItem(UI_THEME_STORAGE_KEY, id);
  } catch {
    // Без localStorage тема действует до перезагрузки.
  }
}

export function applyUiTheme(id: UiThemeId, root: HTMLElement = document.documentElement) {
  const theme = getUiTheme(id);
  root.dataset.uiTheme = theme.id;
  root.dataset.theme = theme.scheme;
}
