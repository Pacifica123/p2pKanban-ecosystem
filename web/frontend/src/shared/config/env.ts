function resolveBooleanEnv(value: string | undefined, fallback: boolean) {
  if (value === undefined) return fallback;
  const normalized = value.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
  return fallback;
}

export const env = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL?.trim() || 'http://127.0.0.1:18080/api/v1').replace(/\/$/, ''),
  enableProjectRoadmapSeed: resolveBooleanEnv(import.meta.env.VITE_ENABLE_PROJECT_ROADMAP_SEED, true),
};
