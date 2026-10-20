import type { PropsWithChildren } from 'react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { useNetwork } from '../../app/NetworkProvider';
import { isNetworkError } from '../../shared/api/client';
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
    // An offline session waits for the node to confirm the sign-in; then this runs again.
    if (!isOnline || auth.isOfflineSession) {
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
  }, [auth.isOfflineSession, auth.status, auth.user?.id, isOnline]);

  useEffect(() => {
    setHydrated(false);
    void refresh();
  }, [refresh]);

  // One request at a time: taps made while it is on the way are merged into the
  // pending patch and go in the next request. A node that does not answer keeps
  // the change on the device (as the settings screen promises) instead of
  // reverting it 12 s later.
  const sendingRef = useRef(false);
  const savePreferences = useCallback(async (
    patch: UpdateUserAppearancePreferencesRequest,
  ) => {
    const optimistic = {
      ...preferences,
      ...patch,
      isCustomized: true,
      updatedAt: new Date().toISOString(),
    };
    setPreferences(optimistic);
    await writeSessionJson(CACHE_KEY, optimistic);
    const queued = await readSessionJson<UpdateUserAppearancePreferencesRequest>(
      PENDING_KEY,
      {},
    );
    await writeSessionJson(PENDING_KEY, { ...queued, ...patch });
    if (!isOnline || auth.isOfflineSession || sendingRef.current) return;
    sendingRef.current = true;
    setSaving(true);
    try {
      for (;;) {
        const request = await readSessionJson<UpdateUserAppearancePreferencesRequest | null>(PENDING_KEY, null);
        if (!request || !Object.keys(request).length) return;
        const saved = await updateMyAppearance(request);
        const after = await readSessionJson<UpdateUserAppearancePreferencesRequest | null>(PENDING_KEY, null);
        if (JSON.stringify(after) !== JSON.stringify(request)) continue;
        await writeSessionJson(CACHE_KEY, saved);
        await removeSessionValue(PENDING_KEY);
        setPreferences(saved);
        return;
      }
    } catch (error) {
      if (isNetworkError(error)) return;
      // The node refused the change: show what it keeps.
      await removeSessionValue(PENDING_KEY);
      void refresh();
      throw error;
    } finally {
      sendingRef.current = false;
      setSaving(false);
    }
  }, [auth.isOfflineSession, isOnline, preferences, refresh]);

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
