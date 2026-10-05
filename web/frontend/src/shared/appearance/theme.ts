import type { CSSProperties } from 'react';
import type { AppTheme, BoardAppearanceSettings, UserAppearancePreferences, WallpaperConfig } from '@/shared/types/api';

type CssVariableMap = Record<`--${string}`, string>;

export type ResolvedThemeMode = 'light' | 'dark';

export interface BoardPresetDefinition {
  id: string;
  label: string;
  description: string;
  preview: string;
  wallpaperPreset: string;
  variables: CssVariableMap;
  previewByMode?: Partial<Record<ResolvedThemeMode, string>>;
  wallpaperPresetByMode?: Partial<Record<ResolvedThemeMode, string>>;
  variablesByMode?: Partial<Record<ResolvedThemeMode, CssVariableMap>>;
}

const systemPreset: BoardPresetDefinition = {
  id: 'system',
  label: 'System',
  description: 'Нейтральный preset, опирается на текущую app theme.',
  preview: 'linear-gradient(135deg, rgba(59,130,246,0.25), rgba(15,23,42,0.96))',
  wallpaperPreset: 'aurora',
  variables: {
    '--bg': '#09111f',
    '--bg-soft': '#0f172a',
    '--bg-elevated': '#111c34',
    '--bg-card': '#13203d',
    '--surface-border': 'rgba(148, 163, 184, 0.18)',
    '--surface-strong': 'rgba(148, 163, 184, 0.32)',
    '--text': '#e2e8f0',
    '--text-soft': '#94a3b8',
    '--accent': '#60a5fa',
    '--accent-strong': '#3b82f6',
    '--shadow': '0 20px 50px rgba(2, 6, 23, 0.45)',
  },
  previewByMode: {
    light: 'linear-gradient(135deg, rgba(37, 99, 235, 0.16), rgba(255,255,255,0.96))',
  },
  wallpaperPresetByMode: {
    light: 'aurora',
  },
  variablesByMode: {
    light: {
      '--bg': '#edf3ff',
      '--bg-soft': '#f8fbff',
      '--bg-elevated': '#ffffff',
      '--bg-card': '#ffffff',
      '--surface-border': 'rgba(148, 163, 184, 0.28)',
      '--surface-strong': 'rgba(71, 85, 105, 0.28)',
      '--text': '#0f172a',
      '--text-soft': '#475569',
      '--accent': '#2563eb',
      '--accent-strong': '#1d4ed8',
      '--shadow': '0 20px 45px rgba(148, 163, 184, 0.18)',
    },
  },
};

export const BOARD_THEME_PRESETS: BoardPresetDefinition[] = [
  systemPreset,
  {
    id: 'midnight-blue',
    label: 'Midnight blue',
    description: 'Холодный насыщенный preset для ночных board.',
    preview: 'linear-gradient(135deg, rgba(37, 99, 235, 0.4), rgba(15, 23, 42, 0.92))',
    wallpaperPreset: 'blueprint',
    variables: {
      '--bg': '#081124',
      '--bg-soft': '#0d1833',
      '--bg-elevated': '#112048',
      '--bg-card': '#17305d',
      '--surface-border': 'rgba(125, 211, 252, 0.18)',
      '--surface-strong': 'rgba(96, 165, 250, 0.34)',
      '--text': '#dbeafe',
      '--text-soft': '#93c5fd',
      '--accent': '#38bdf8',
      '--accent-strong': '#0ea5e9',
      '--shadow': '0 24px 52px rgba(2, 6, 23, 0.58)',
    },
    previewByMode: {
      light: 'linear-gradient(135deg, rgba(96, 165, 250, 0.22), rgba(239,246,255,0.96))',
    },
    wallpaperPresetByMode: {
      light: 'blueprint',
    },
    variablesByMode: {
      light: {
        '--bg': '#eef6ff',
        '--bg-soft': '#f7fbff',
        '--bg-elevated': '#ffffff',
        '--bg-card': '#ffffff',
        '--surface-border': 'rgba(96, 165, 250, 0.24)',
        '--surface-strong': 'rgba(59, 130, 246, 0.22)',
        '--text': '#13213c',
        '--text-soft': '#44617f',
        '--accent': '#2563eb',
        '--accent-strong': '#1d4ed8',
        '--shadow': '0 20px 44px rgba(96, 165, 250, 0.16)',
      },
    },
  },
  {
    id: 'forest-mint',
    label: 'Forest mint',
    description: 'Более спокойная зелёная палитра для focus board.',
    preview: 'linear-gradient(135deg, rgba(16, 185, 129, 0.34), rgba(17, 24, 39, 0.96))',
    wallpaperPreset: 'canopy',
    variables: {
      '--bg': '#071712',
      '--bg-soft': '#0d211b',
      '--bg-elevated': '#123128',
      '--bg-card': '#173b31',
      '--surface-border': 'rgba(110, 231, 183, 0.18)',
      '--surface-strong': 'rgba(52, 211, 153, 0.34)',
      '--text': '#d1fae5',
      '--text-soft': '#86efac',
      '--accent': '#34d399',
      '--accent-strong': '#10b981',
      '--shadow': '0 24px 52px rgba(3, 15, 11, 0.58)',
    },
    previewByMode: {
      light: 'linear-gradient(135deg, rgba(52, 211, 153, 0.22), rgba(236,253,245,0.96))',
    },
    wallpaperPresetByMode: {
      light: 'canopy',
    },
    variablesByMode: {
      light: {
        '--bg': '#effcf6',
        '--bg-soft': '#f7fefb',
        '--bg-elevated': '#ffffff',
        '--bg-card': '#ffffff',
        '--surface-border': 'rgba(52, 211, 153, 0.24)',
        '--surface-strong': 'rgba(16, 185, 129, 0.22)',
        '--text': '#123126',
        '--text-soft': '#3f6f61',
        '--accent': '#10b981',
        '--accent-strong': '#059669',
        '--shadow': '0 20px 44px rgba(52, 211, 153, 0.16)',
      },
    },
  },
  {
    id: 'sunrise-coral',
    label: 'Sunrise coral',
    description: 'Тёплый preset для более живого board surface.',
    preview: 'linear-gradient(135deg, rgba(251, 146, 60, 0.4), rgba(124, 45, 18, 0.96))',
    wallpaperPreset: 'sunrise',
    variables: {
      '--bg': '#22110b',
      '--bg-soft': '#30170f',
      '--bg-elevated': '#472314',
      '--bg-card': '#5b2e18',
      '--surface-border': 'rgba(253, 186, 116, 0.2)',
      '--surface-strong': 'rgba(251, 146, 60, 0.34)',
      '--text': '#ffedd5',
      '--text-soft': '#fdba74',
      '--accent': '#fb923c',
      '--accent-strong': '#f97316',
      '--shadow': '0 24px 52px rgba(30, 12, 8, 0.58)',
    },
    previewByMode: {
      light: 'linear-gradient(135deg, rgba(251, 146, 60, 0.2), rgba(255,247,237,0.96))',
    },
    wallpaperPresetByMode: {
      light: 'sunrise',
    },
    variablesByMode: {
      light: {
        '--bg': '#fff5ef',
        '--bg-soft': '#fffaf7',
        '--bg-elevated': '#ffffff',
        '--bg-card': '#ffffff',
        '--surface-border': 'rgba(251, 146, 60, 0.24)',
        '--surface-strong': 'rgba(249, 115, 22, 0.22)',
        '--text': '#3a1f15',
        '--text-soft': '#7b5342',
        '--accent': '#ea580c',
        '--accent-strong': '#c2410c',
        '--shadow': '0 20px 44px rgba(251, 146, 60, 0.16)',
      },
    },
  },
  {
    id: 'plum-ink',
    label: 'Plum ink',
    description: 'Контрастный фиолетовый preset для экспериментальных board.',
    preview: 'linear-gradient(135deg, rgba(168, 85, 247, 0.38), rgba(49, 46, 129, 0.96))',
    wallpaperPreset: 'nebula',
    variables: {
      '--bg': '#130a1f',
      '--bg-soft': '#1c102b',
      '--bg-elevated': '#291745',
      '--bg-card': '#341d59',
      '--surface-border': 'rgba(196, 181, 253, 0.18)',
      '--surface-strong': 'rgba(168, 85, 247, 0.34)',
      '--text': '#ede9fe',
      '--text-soft': '#c4b5fd',
      '--accent': '#a855f7',
      '--accent-strong': '#9333ea',
      '--shadow': '0 24px 52px rgba(12, 7, 23, 0.62)',
    },
    previewByMode: {
      light: 'linear-gradient(135deg, rgba(192, 132, 252, 0.22), rgba(250,245,255,0.96))',
    },
    wallpaperPresetByMode: {
      light: 'nebula',
    },
    variablesByMode: {
      light: {
        '--bg': '#faf5ff',
        '--bg-soft': '#fcf9ff',
        '--bg-elevated': '#ffffff',
        '--bg-card': '#ffffff',
        '--surface-border': 'rgba(168, 85, 247, 0.22)',
        '--surface-strong': 'rgba(147, 51, 234, 0.18)',
        '--text': '#2e1f4f',
        '--text-soft': '#6e5b98',
        '--accent': '#9333ea',
        '--accent-strong': '#7e22ce',
        '--shadow': '0 20px 44px rgba(168, 85, 247, 0.16)',
      },
    },
  },
];

const WALLPAPER_PRESETS: Record<string, Record<ResolvedThemeMode, string>> = {
  aurora: {
    dark: 'radial-gradient(circle at top left, rgba(96,165,250,0.24), transparent 30%), radial-gradient(circle at bottom right, rgba(59,130,246,0.18), transparent 28%), linear-gradient(180deg, rgba(9,17,31,0.98), rgba(15,23,42,0.98))',
    light: 'radial-gradient(circle at top left, rgba(96,165,250,0.16), transparent 30%), radial-gradient(circle at bottom right, rgba(37,99,235,0.12), transparent 28%), linear-gradient(180deg, rgba(248,251,255,0.98), rgba(237,243,255,0.98))',
  },
  blueprint: {
    dark: 'linear-gradient(135deg, rgba(56,189,248,0.15), transparent 18%), linear-gradient(225deg, rgba(59,130,246,0.12), transparent 16%), linear-gradient(180deg, rgba(8,17,36,0.98), rgba(13,24,51,0.98))',
    light: 'linear-gradient(135deg, rgba(96,165,250,0.16), transparent 18%), linear-gradient(225deg, rgba(59,130,246,0.12), transparent 16%), linear-gradient(180deg, rgba(247,251,255,0.98), rgba(238,246,255,0.98))',
  },
  canopy: {
    dark: 'radial-gradient(circle at top, rgba(52,211,153,0.18), transparent 22%), linear-gradient(160deg, rgba(7,23,18,0.98), rgba(13,33,27,0.98))',
    light: 'radial-gradient(circle at top, rgba(52,211,153,0.14), transparent 22%), linear-gradient(160deg, rgba(247,254,251,0.98), rgba(239,252,246,0.98))',
  },
  sunrise: {
    dark: 'radial-gradient(circle at top, rgba(251,146,60,0.22), transparent 22%), linear-gradient(160deg, rgba(34,17,11,0.98), rgba(71,35,20,0.98))',
    light: 'radial-gradient(circle at top, rgba(251,146,60,0.16), transparent 22%), linear-gradient(160deg, rgba(255,250,247,0.98), rgba(255,245,239,0.98))',
  },
  nebula: {
    dark: 'radial-gradient(circle at top left, rgba(168,85,247,0.2), transparent 26%), linear-gradient(160deg, rgba(19,10,31,0.98), rgba(41,23,69,0.98))',
    light: 'radial-gradient(circle at top left, rgba(192,132,252,0.16), transparent 26%), linear-gradient(160deg, rgba(252,249,255,0.98), rgba(250,245,255,0.98))',
  },
};

export function resolveSystemTheme(appTheme: AppTheme, systemPrefersDark: boolean): ResolvedThemeMode {
  if (appTheme === 'system') return systemPrefersDark ? 'dark' : 'light';
  return appTheme;
}

function resolvePresetVariables(preset: BoardPresetDefinition, themeMode: ResolvedThemeMode) {
  return preset.variablesByMode?.[themeMode] || preset.variables;
}

function resolvePresetPreview(preset: BoardPresetDefinition, themeMode: ResolvedThemeMode) {
  return preset.previewByMode?.[themeMode] || preset.preview;
}

function resolvePresetWallpaperKey(preset: BoardPresetDefinition, themeMode: ResolvedThemeMode) {
  return preset.wallpaperPresetByMode?.[themeMode] || preset.wallpaperPreset;
}

export function getBoardPresetDefinition(presetId?: string | null) {
  return BOARD_THEME_PRESETS.find((item) => item.id === presetId) || systemPreset;
}

export function getBoardPresetPreview(presetId: string | null | undefined, themeMode: ResolvedThemeMode = 'dark') {
  const preset = getBoardPresetDefinition(presetId);
  return resolvePresetPreview(preset, themeMode);
}

export function getBoardAccentColor(appearance: Pick<BoardAppearanceSettings, 'customProperties'>) {
  const value = appearance.customProperties?.accentColor;
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : null;
}

function getAccentPalette(accentColor: string, themeMode: ResolvedThemeMode): CssVariableMap {
  if (themeMode === 'light') {
    return {
      '--bg-elevated': `color-mix(in srgb, ${accentColor} 10%, #ffffff)`,
      '--bg-soft': `color-mix(in srgb, ${accentColor} 18%, #e8eef5)`,
      '--bg-card': `color-mix(in srgb, ${accentColor} 7%, #ffffff)`,
      '--surface-border': `color-mix(in srgb, ${accentColor} 28%, rgba(71, 85, 105, 0.22))`,
      '--surface-strong': `color-mix(in srgb, ${accentColor} 42%, rgba(71, 85, 105, 0.24))`,
      '--accent': accentColor,
      '--accent-strong': `color-mix(in srgb, ${accentColor} 82%, #111827)`,
    };
  }

  return {
    '--bg-elevated': `color-mix(in srgb, ${accentColor} 19%, #0b1220)`,
    '--bg-soft': `color-mix(in srgb, ${accentColor} 25%, #101827)`,
    '--bg-card': `color-mix(in srgb, ${accentColor} 14%, #050914)`,
    '--surface-border': `color-mix(in srgb, ${accentColor} 30%, rgba(148, 163, 184, 0.15))`,
    '--surface-strong': `color-mix(in srgb, ${accentColor} 48%, rgba(148, 163, 184, 0.18))`,
    '--accent': accentColor,
    '--accent-strong': `color-mix(in srgb, ${accentColor} 78%, #ffffff)`,
  };
}

export function getWallpaperBackground(
  wallpaper: WallpaperConfig,
  presetId?: string | null,
  themeMode: ResolvedThemeMode = 'dark',
  accentColor?: string | null,
) {
  const preset = getBoardPresetDefinition(presetId);
  const presetWallpaperKey = resolvePresetWallpaperKey(preset, themeMode);

  if (wallpaper.kind === 'none') return resolvePresetPreview(preset, themeMode);
  if (wallpaper.kind === 'accent') {
    const accent = accentColor || resolvePresetVariables(preset, themeMode)['--accent'];
    const base = themeMode === 'light' ? '#f8fafc' : '#070b14';
    return `radial-gradient(circle at top left, color-mix(in srgb, ${accent} 34%, transparent), transparent 38%), linear-gradient(145deg, color-mix(in srgb, ${accent} 18%, ${base}), ${base})`;
  }
  if ((wallpaper.kind === 'solid' || wallpaper.kind === 'gradient') && wallpaper.value) return wallpaper.value;
  if (wallpaper.kind === 'preset' && wallpaper.value) {
    return WALLPAPER_PRESETS[wallpaper.value]?.[themeMode]
      || WALLPAPER_PRESETS[presetWallpaperKey]?.[themeMode]
      || resolvePresetPreview(preset, themeMode);
  }
  return WALLPAPER_PRESETS[presetWallpaperKey]?.[themeMode] || resolvePresetPreview(preset, themeMode);
}

export function getBoardThemeStyle(
  appearance: BoardAppearanceSettings,
  themeMode: ResolvedThemeMode = 'dark',
): CSSProperties {
  const preset = getBoardPresetDefinition(appearance.themePreset);
  const accentColor = getBoardAccentColor(appearance);
  const style: CSSProperties & CssVariableMap = {
    ...resolvePresetVariables(preset, themeMode),
    ...(accentColor ? getAccentPalette(accentColor, themeMode) : {}),
    '--board-column-width': appearance.columnDensity === 'compact' ? '280px' : '320px',
    '--board-card-gap': appearance.columnDensity === 'compact' ? '10px' : '12px',
    '--board-info-scrim': themeMode === 'light'
      ? 'rgba(255, 255, 255, 0.76)'
      : 'rgba(2, 6, 23, 0.68)',
  };
  return style;
}

export function getBoardSurfaceStyle(
  appearance: BoardAppearanceSettings,
  themeMode: ResolvedThemeMode = 'dark',
): CSSProperties {
  const preset = getBoardPresetDefinition(appearance.themePreset);
  const accentColor = getBoardAccentColor(appearance);
  const style: CSSProperties & CssVariableMap = {
    ...getBoardThemeStyle(appearance, themeMode),
    background: getWallpaperBackground(
      appearance.wallpaper,
      appearance.themePreset,
      themeMode,
      accentColor,
    ),
  };
  if (appearance.wallpaper.kind === 'image' && appearance.wallpaper.value) {
    style.backgroundColor = resolvePresetVariables(preset, themeMode)['--bg'];
    const imageWash = themeMode === 'light'
      ? 'rgba(255, 255, 255, 0.08)'
      : 'rgba(2, 6, 23, 0.12)';
    style.backgroundImage = `linear-gradient(${imageWash}, ${imageWash}), url(${JSON.stringify(appearance.wallpaper.value)})`;
    style.backgroundPosition = 'center';
    style.backgroundRepeat = 'no-repeat';
    style.backgroundSize = 'cover';
  }
  return style;
}

export function buildUserAppearancePreview(base: UserAppearancePreferences, patch: Partial<UserAppearancePreferences>) {
  return {
    ...base,
    ...patch,
  } satisfies UserAppearancePreferences;
}
