import { readFileSync } from 'node:fs';
import path from 'node:path';
import { getBoardSurfaceStyle } from '@/shared/appearance/theme';
import {
  DEFAULT_UI_THEME,
  UI_THEMES,
  UI_THEME_STORAGE_KEY,
  applyUiTheme,
  normalizeUiTheme,
  readStoredUiTheme,
  writeStoredUiTheme,
} from '@/shared/appearance/uiThemes';
import type { BoardAppearanceSettings } from '@/shared/types/api';

const TOKENS = [
  'background', 'surface', 'surface-muted', 'surface-raised', 'border', 'border-strong',
  'text', 'text-muted', 'accent', 'accent-strong', 'accent-soft', 'accent-text', 'on-accent',
  'danger', 'danger-text', 'success', 'success-text', 'warning', 'warning-text', 'overlay',
];

const themesCss = readFileSync(path.resolve(__dirname, '../../../../app/styles/themes.css'), 'utf8');

function themeBlock(id: string) {
  const match = themesCss.match(new RegExp(`:root\\[data-ui-theme='${id}'\\] \\{([^}]*)\\}`));
  return match?.[1] || '';
}

describe('app ui themes', () => {
  it('offers the four themes and graphite by default', () => {
    expect(UI_THEMES.map((theme) => theme.id)).toEqual(['graphite', 'lemon', 'azure', 'silver']);
    expect(DEFAULT_UI_THEME).toBe('graphite');
    expect(normalizeUiTheme('dark')).toBe('graphite');
    expect(normalizeUiTheme(null)).toBe('graphite');
    expect(normalizeUiTheme('azure')).toBe('azure');
  });

  it('declares every dictionary token for every theme in themes.css', () => {
    for (const theme of UI_THEMES) {
      const block = themeBlock(theme.id);
      for (const token of TOKENS) expect(block, `${theme.id} --ui-${token}`).toContain(`--ui-${token}:`);
      for (const swatch of Object.values(theme.swatches)) expect(themesCss).toContain(swatch);
    }
    expect(themesCss).toMatch(/:root,\s*:root\[data-ui-theme='graphite'\]/);
  });

  it('keeps the choice on the device and sets the colour scheme', () => {
    window.localStorage.removeItem(UI_THEME_STORAGE_KEY);
    expect(readStoredUiTheme()).toBe('graphite');
    writeStoredUiTheme('lemon');
    expect(window.localStorage.getItem('p2p-kanban.ui-theme')).toBe('lemon');
    expect(readStoredUiTheme()).toBe('lemon');

    const root = document.createElement('html');
    applyUiTheme('lemon', root);
    expect(root.dataset.uiTheme).toBe('lemon');
    expect(root.dataset.theme).toBe('light');
    applyUiTheme('graphite', root);
    expect(root.dataset.theme).toBe('dark');
    window.localStorage.removeItem(UI_THEME_STORAGE_KEY);
  });

  it('lets the System board preset follow the app theme', () => {
    const appearance: BoardAppearanceSettings = {
      boardId: 'board-1',
      isCustomized: false,
      themePreset: 'system',
      wallpaper: { kind: 'none', value: null },
      columnDensity: 'comfortable',
      cardPreviewMode: 'expanded',
      showCardDescription: true,
      showCardDates: true,
      showChecklistProgress: true,
      customProperties: {},
    };
    const style = getBoardSurfaceStyle(appearance, 'light') as Record<string, string>;
    expect(style['--bg']).toBe('var(--ui-background)');
    expect(style['--bg-card']).toBe('var(--ui-surface-raised)');
    expect(style.background).toBe('var(--ui-background)');
  });
});
