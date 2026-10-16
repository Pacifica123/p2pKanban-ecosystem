import { DEFAULT_UI_THEME, UI_THEMES, getUiTheme, mixHex, normalizeUiTheme } from './uiThemes';

const TOKENS = [
  'background', 'surface', 'surfaceMuted', 'surfaceRaised', 'border', 'borderStrong',
  'text', 'textMuted', 'accent', 'accentStrong', 'accentSoft', 'accentText', 'onAccent',
  'danger', 'dangerText', 'success', 'successText', 'warning', 'warningText', 'overlay',
];

describe('mobile ui themes', () => {
  it('offers the four ecosystem themes with graphite by default', () => {
    expect(UI_THEMES.map((theme) => theme.id)).toEqual(['graphite', 'lemon', 'azure', 'silver']);
    expect(DEFAULT_UI_THEME).toBe('graphite');
    expect(getUiTheme('graphite').scheme).toBe('dark');
    expect(UI_THEMES.filter((theme) => theme.scheme === 'light')).toHaveLength(3);
  });

  it('treats old or unknown stored values as graphite', () => {
    expect(normalizeUiTheme(null)).toBe('graphite');
    expect(normalizeUiTheme('dark')).toBe('graphite');
    expect(normalizeUiTheme('system')).toBe('graphite');
    expect(normalizeUiTheme('lemon')).toBe('lemon');
  });

  it('keeps every dictionary token in every theme', () => {
    for (const theme of UI_THEMES) {
      expect(Object.keys(theme.colors).sort()).toEqual([...TOKENS].sort());
    }
  });

  it('mixes hex colours deterministically', () => {
    expect(mixHex('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mixHex('#da4453', '#292c30', 1)).toBe('#da4453');
  });
});
