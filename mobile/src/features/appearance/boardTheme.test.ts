import {
  defaultBoardAppearance,
  resolveBoardPalette,
  validHex,
} from './boardTheme';

describe('mobile board appearance', () => {
  it('uses the same named palette and custom accent as web', () => {
    const appearance = {
      ...defaultBoardAppearance('board-1'),
      themePreset: 'forest-mint',
      customProperties: { accentColor: '#A855F7' },
    };
    expect(resolveBoardPalette(appearance, 'dark').accent).toBe('#a855f7');
  });

  it('adapts web gradients to a deterministic flat background', () => {
    const appearance = {
      ...defaultBoardAppearance('board-1'),
      wallpaper: {
        kind: 'gradient' as const,
        value: 'linear-gradient(135deg, #1e293b, #0f172a)',
      },
    };
    expect(resolveBoardPalette(appearance, 'dark').background).toBe('#1e293b');
  });

  it('accepts only http(s) image wallpapers and six-digit colors', () => {
    const remote = {
      ...defaultBoardAppearance('board-1'),
      wallpaper: { kind: 'image' as const, value: 'https://example.org/wall.jpg' },
    };
    const local = {
      ...remote,
      wallpaper: { kind: 'image' as const, value: 'file:///private/wall.jpg' },
    };
    expect(resolveBoardPalette(remote, 'light').imageUri).toContain('https://');
    expect(resolveBoardPalette(local, 'light').imageUri).toBeNull();
    expect(validHex('#60a5fa')).toBe(true);
    expect(validHex('#abc')).toBe(false);
  });
});
