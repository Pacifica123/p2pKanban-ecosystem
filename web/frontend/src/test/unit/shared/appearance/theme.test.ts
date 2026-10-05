import {
  getBoardAccentColor,
  getBoardSurfaceStyle,
} from '@/shared/appearance/theme';
import type { BoardAppearanceSettings } from '@/shared/types/api';

function appearance(
  patch: Partial<BoardAppearanceSettings> = {},
): BoardAppearanceSettings {
  return {
    boardId: 'board-1',
    isCustomized: true,
    themePreset: 'system',
    wallpaper: { kind: 'none', value: null },
    columnDensity: 'comfortable',
    cardPreviewMode: 'expanded',
    showCardDescription: true,
    showCardDates: true,
    showChecklistProgress: true,
    customProperties: {},
    ...patch,
  };
}

describe('board accent palette', () => {
  it('uses a valid custom accent and derives opposite card contrast by theme', () => {
    const value = appearance({ customProperties: { accentColor: '#A855F7' } });
    const dark = getBoardSurfaceStyle(value, 'dark') as Record<string, string>;
    const light = getBoardSurfaceStyle(value, 'light') as Record<string, string>;

    expect(getBoardAccentColor(value)).toBe('#a855f7');
    expect(dark['--bg-card']).toContain('#050914');
    expect(light['--bg-card']).toContain('#ffffff');
    expect(dark['--accent']).toBe('#a855f7');
  });

  it('does not replace an existing wallpaper when the accent changes', () => {
    const style = getBoardSurfaceStyle(appearance({
      wallpaper: { kind: 'image', value: 'https://example.org/wallpaper.webp' },
      customProperties: { accentColor: '#22c55e' },
    }), 'dark');

    expect(style.backgroundImage).toContain('https://example.org/wallpaper.webp');
    expect(style.backgroundSize).toBe('cover');
  });

  it('builds the optional board background from the active accent', () => {
    const style = getBoardSurfaceStyle(appearance({
      wallpaper: { kind: 'accent', value: null },
      customProperties: { accentColor: '#f97316' },
    }), 'light');

    expect(style.background).toContain('#f97316');
  });
});
