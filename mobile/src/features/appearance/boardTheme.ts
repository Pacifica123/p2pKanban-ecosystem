import type {
  BoardAppearanceSettings,
  WallpaperConfig,
} from '../../shared/types/api';

export type ResolvedBoardMode = 'light' | 'dark';

export interface BoardPalette {
  background: string;
  column: string;
  card: string;
  text: string;
  muted: string;
  border: string;
  accent: string;
  imageUri: string | null;
}

type PresetPalette = Omit<BoardPalette, 'imageUri'>;

const palettes: Record<string, Record<ResolvedBoardMode, PresetPalette>> = {
  system: {
    dark: {
      background: '#09111f', column: '#0f172a', card: '#13203d',
      text: '#e2e8f0', muted: '#94a3b8', border: '#334155', accent: '#60a5fa',
    },
    light: {
      background: '#edf3ff', column: '#f8fbff', card: '#ffffff',
      text: '#0f172a', muted: '#475569', border: '#cbd5e1', accent: '#2563eb',
    },
  },
  'midnight-blue': {
    dark: {
      background: '#081124', column: '#0d1833', card: '#17305d',
      text: '#dbeafe', muted: '#93c5fd', border: '#28507f', accent: '#38bdf8',
    },
    light: {
      background: '#eef6ff', column: '#f7fbff', card: '#ffffff',
      text: '#13213c', muted: '#44617f', border: '#bfdbfe', accent: '#2563eb',
    },
  },
  'forest-mint': {
    dark: {
      background: '#071712', column: '#0d211b', card: '#173b31',
      text: '#d1fae5', muted: '#86efac', border: '#27634f', accent: '#34d399',
    },
    light: {
      background: '#effcf6', column: '#f7fefb', card: '#ffffff',
      text: '#123126', muted: '#3f6f61', border: '#a7f3d0', accent: '#10b981',
    },
  },
  'sunrise-coral': {
    dark: {
      background: '#22110b', column: '#30170f', card: '#5b2e18',
      text: '#ffedd5', muted: '#fdba74', border: '#7c3d1e', accent: '#fb923c',
    },
    light: {
      background: '#fff5ef', column: '#fffaf7', card: '#ffffff',
      text: '#3a1f15', muted: '#7b5342', border: '#fed7aa', accent: '#ea580c',
    },
  },
  'plum-ink': {
    dark: {
      background: '#130a1f', column: '#1c102b', card: '#341d59',
      text: '#ede9fe', muted: '#c4b5fd', border: '#5b3487', accent: '#a855f7',
    },
    light: {
      background: '#faf5ff', column: '#fcf9ff', card: '#ffffff',
      text: '#2e1f4f', muted: '#6e5b98', border: '#e9d5ff', accent: '#9333ea',
    },
  },
};

const wallpaperColors: Record<string, Record<ResolvedBoardMode, string>> = {
  aurora: { dark: '#0f1d35', light: '#edf3ff' },
  blueprint: { dark: '#0d1833', light: '#eef6ff' },
  canopy: { dark: '#0d211b', light: '#effcf6' },
  sunrise: { dark: '#472314', light: '#fff5ef' },
  nebula: { dark: '#291745', light: '#faf5ff' },
};

export const boardThemePresets = [
  { id: 'system', label: 'System' },
  { id: 'midnight-blue', label: 'Midnight blue' },
  { id: 'forest-mint', label: 'Forest mint' },
  { id: 'sunrise-coral', label: 'Sunrise coral' },
  { id: 'plum-ink', label: 'Plum ink' },
] as const;

export const boardWallpaperPresets = [
  'aurora', 'blueprint', 'canopy', 'sunrise', 'nebula',
] as const;

export function defaultBoardAppearance(boardId: string): BoardAppearanceSettings {
  return {
    boardId,
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
}

export function validHex(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
}

function firstHex(value: string | null | undefined) {
  return value?.match(/#[0-9a-f]{6}/i)?.[0] || null;
}

function customAccent(appearance: BoardAppearanceSettings) {
  const value = appearance.customProperties?.accentColor;
  return validHex(value) ? value.toLowerCase() : null;
}

function wallpaperBackground(
  wallpaper: WallpaperConfig,
  mode: ResolvedBoardMode,
  fallback: string,
  accent: string,
) {
  if (wallpaper.kind === 'accent') return accent;
  if (wallpaper.kind === 'solid' && validHex(wallpaper.value)) return wallpaper.value;
  if (wallpaper.kind === 'gradient') return firstHex(wallpaper.value) || fallback;
  if (wallpaper.kind === 'preset' && wallpaper.value) {
    return wallpaperColors[wallpaper.value]?.[mode] || fallback;
  }
  return fallback;
}

export function resolveBoardPalette(
  appearance: BoardAppearanceSettings,
  mode: ResolvedBoardMode,
): BoardPalette {
  const base = (palettes[appearance.themePreset] || palettes.system)![mode];
  const accent = customAccent(appearance) || base.accent;
  const imageUri = appearance.wallpaper.kind === 'image'
    && typeof appearance.wallpaper.value === 'string'
    && /^https?:\/\//i.test(appearance.wallpaper.value)
    ? appearance.wallpaper.value
    : null;
  return {
    ...base,
    accent,
    background: wallpaperBackground(
      appearance.wallpaper,
      mode,
      base.background,
      accent,
    ),
    imageUri,
  };
}
