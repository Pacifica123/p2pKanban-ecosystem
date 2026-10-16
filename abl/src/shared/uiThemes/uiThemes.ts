// Темы интерфейса приложения: словарь p2p-kanban-ui-themes/1
// (docs/ecosystem/ui-themes.md в корне монорепозитория). Цвета — src/themes.css.
export type UiThemeId = "graphite" | "lemon" | "azure" | "silver";
export type UiScheme = "light" | "dark";

export interface UiThemeDefinition {
  id: UiThemeId;
  label: string;
  description: string;
  scheme: UiScheme;
}

export const DEFAULT_UI_THEME: UiThemeId = "graphite";

export const UI_THEMES: readonly UiThemeDefinition[] = [
  { id: "graphite", label: "Графит", description: "Тёмно-серая рабочая", scheme: "dark" },
  { id: "lemon", label: "Лимон", description: "Светло-жёлтая flat", scheme: "light" },
  { id: "azure", label: "Лазурь", description: "Светло-синяя flat", scheme: "light" },
  { id: "silver", label: "Серебро", description: "Светло-серая flat", scheme: "light" },
];

export function normalizeUiTheme(value: unknown): UiThemeId {
  return UI_THEMES.some((theme) => theme.id === value) ? (value as UiThemeId) : DEFAULT_UI_THEME;
}

export function getUiTheme(value: unknown): UiThemeDefinition {
  const id = normalizeUiTheme(value);
  return UI_THEMES.find((theme) => theme.id === id)!;
}

// Хранилища браузера во фронтенде abl запрещены (проверки A07–A09: всё
// долговременное живёт за границей Rust core). Пока выбор держится до
// перезапуска окна, при старте всегда graphite; запоминание через Rust core —
// отдельная карточка на доске экосистемы.
export function applyUiTheme(id: UiThemeId, root: HTMLElement = document.documentElement) {
  const theme = getUiTheme(id);
  root.dataset.uiTheme = theme.id;
  root.dataset.uiScheme = theme.scheme;
}
