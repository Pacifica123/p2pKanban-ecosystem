import type { PropsWithChildren } from 'react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { useNetwork } from '../../app/NetworkProvider';
import { getMyAppearance, updateMyAppearance } from '../../shared/api/endpoints';
import {
  readSessionJson,
  removeSessionValue,
  writeSessionJson,
} from '../../shared/storage/storage';
import type {
  UpdateUserAppearancePreferencesRequest,
  UserAppearancePreferences,
} from '../../shared/types/api';
import { useAuth } from '../auth/AuthProvider';

const CACHE_KEY = 'appearance/user';
const PENDING_KEY = 'appearance/user-pending';

function defaults(userId = ''): UserAppearancePreferences {
  return {
    userId,
    isCustomized: false,
    appTheme: 'system',
    density: 'comfortable',
    reduceMotion: false,
    checklistItemSubmitMode: 'ctrl_enter',
    cardDetailsMode: 'drawer',
  };
}

interface AppearanceContextValue {
  preferences: UserAppearancePreferences;
  hydrated: boolean;
  saving: boolean;
  savePreferences: (patch: UpdateUserAppearancePreferencesRequest) => Promise<void>;
  refresh: () => Promise<void>;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function AppearanceProvider({ children }: PropsWithChildren) {
  const auth = useAuth();
  const { isOnline } = useNetwork();
  const [preferences, setPreferences] = useState(() => defaults());
  const [hydrated, setHydrated] = useState(false);
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    if (auth.status !== 'authenticated' || !auth.user) {
      setPreferences(defaults());
      setHydrated(true);
      return;
    }
    const cached = await readSessionJson<UserAppearancePreferences | null>(CACHE_KEY, null);
    if (cached) setPreferences({ ...defaults(auth.user.id), ...cached });
    const pending = await readSessionJson<UpdateUserAppearancePreferencesRequest | null>(
      PENDING_KEY,
      null,
    );
    if (!isOnline) {
      if (!cached) setPreferences(defaults(auth.user.id));
      setHydrated(true);
      return;
    }
    try {
      const remote = pending
        ? await updateMyAppearance(pending)
        : await getMyAppearance();
      await writeSessionJson(CACHE_KEY, remote);
      await removeSessionValue(PENDING_KEY);
      setPreferences(remote);
    } catch {
      if (!cached) setPreferences(defaults(auth.user.id));
    } finally {
      setHydrated(true);
    }
  }, [auth.status, auth.user?.id, isOnline]);

  useEffect(() => {
    setHydrated(false);
    void refresh();
  }, [refresh]);

  const savePreferences = useCallback(async (
    patch: UpdateUserAppearancePreferencesRequest,
  ) => {
    const previous = preferences;
    const optimistic = {
      ...previous,
      ...patch,
      isCustomized: true,
      updatedAt: new Date().toISOString(),
    };
    setPreferences(optimistic);
    setSaving(true);
    await writeSessionJson(CACHE_KEY, optimistic);
    const queued = await readSessionJson<UpdateUserAppearancePreferencesRequest>(
      PENDING_KEY,
      {},
    );
    const request = { ...queued, ...patch };
    await writeSessionJson(PENDING_KEY, request);
    try {
      if (!isOnline) return;
      const saved = await updateMyAppearance(request);
      await writeSessionJson(CACHE_KEY, saved);
      await removeSessionValue(PENDING_KEY);
      setPreferences(saved);
    } catch (error) {
      setPreferences(previous);
      await writeSessionJson(CACHE_KEY, previous);
      throw error;
    } finally {
      setSaving(false);
    }
  }, [isOnline, preferences]);

  const value = useMemo<AppearanceContextValue>(() => ({
    preferences,
    hydrated,
    saving,
    savePreferences,
    refresh,
  }), [hydrated, preferences, refresh, savePreferences, saving]);

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error('useAppearance must be used inside AppearanceProvider');
  return value;
}
