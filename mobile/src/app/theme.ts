import { useColorScheme } from 'react-native';

import { useAppearance } from '../features/appearance/AppearanceProvider';
import { useColorOverride } from './ColorOverrideProvider';

export interface AppColors {
  background: string;
  surface: string;
  surfaceMuted: string;
  border: string;
  text: string;
  muted: string;
  accent: string;
  accentSoft: string;
  danger: string;
  dangerSoft: string;
  success: string;
  warning: string;
  overlay: string;
}

export const lightColors: AppColors = {
  background: '#f2f2ee',
  surface: '#ffffff',
  surfaceMuted: '#e9e9e4',
  border: '#d5d5ce',
  text: '#202329',
  muted: '#687078',
  accent: '#6255d9',
  accentSoft: '#e9e6ff',
  danger: '#b33d4b',
  dangerSoft: '#f8e4e7',
  success: '#247a55',
  warning: '#956b18',
  overlay: 'rgba(20, 18, 28, 0.58)',
};

export const darkColors: AppColors = {
  background: '#17151f',
  surface: '#211e2b',
  surfaceMuted: '#2a2635',
  border: '#3b3548',
  text: '#f2eff7',
  muted: '#aaa3b7',
  accent: '#a697ff',
  accentSoft: '#342e55',
  danger: '#ef8290',
  dangerSoft: '#482a33',
  success: '#72d1a7',
  warning: '#dfbd6b',
  overlay: 'rgba(7, 6, 10, 0.72)',
};

export function useAppColors() {
  const base = useResolvedTheme() === 'dark' ? darkColors : lightColors;
  const override = useColorOverride();
  return override ? { ...base, ...override } : base;
}

export function useResolvedTheme() {
  const systemTheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  const { preferences } = useAppearance();
  return preferences.appTheme === 'system' ? systemTheme : preferences.appTheme;
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
