import { useQueryClient } from '@tanstack/react-query';
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
import {
  ApiError,
  setAccessToken,
  setRefreshHandler,
} from '../../shared/api/client';
import {
  getSession,
  nativeRefresh,
  nativeSignIn,
  nativeSignOut,
  nativeSignUp,
  signOutAll,
} from '../../shared/api/endpoints';
import {
  clearSessionBoundStorage,
  loadStoredSession,
  saveStoredSession,
  type StoredNativeSession,
} from '../../shared/storage/storage';
import type { AuthUser, NativeAuthSuccessResponse } from '../../shared/types/api';
import { useConnection } from '../connection/ConnectionProvider';
import { cancelAllCardReminders } from '../reminders/service';

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  sessionId: string | null;
  deviceId: string | null;
  isOfflineSession: boolean;
  signIn: (input: { email: string; password: string }) => Promise<void>;
  signUp: (input: { email: string; password: string; displayName: string }) => Promise<void>;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function expiredSoon(value: string) {
  const numeric = Number(value);
  const epochMilliseconds = Number.isFinite(numeric)
    ? numeric * 1000
    : Date.parse(value);
  return !Number.isFinite(epochMilliseconds) || epochMilliseconds <= Date.now() + 60_000;
}

export function AuthProvider({ children }: PropsWithChildren) {
  const { nodeOrigin } = useConnection();
  const { isOnline } = useNetwork();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [session, setSession] = useState<StoredNativeSession | null>(null);
  const [isOfflineSession, setOfflineSession] = useState(false);
  const sessionRef = useRef<StoredNativeSession | null>(null);
  const generationRef = useRef(0);
  const nativeRefreshPromiseRef = useRef<Promise<string | null> | null>(null);

  const applyStoredSession = useCallback((next: StoredNativeSession | null) => {
    sessionRef.current = next;
    setSession(next);
    setAccessToken(next?.accessToken || null);
    setStatus(next ? 'authenticated' : 'anonymous');
  }, []);

  const applyResponse = useCallback(async (
    response: NativeAuthSuccessResponse,
    expectedNode: string,
  ) => {
    const saved = await saveStoredSession(expectedNode, response);
    applyStoredSession(saved);
    setOfflineSession(false);
    return saved;
  }, [applyStoredSession]);

  const refreshCurrent = useCallback(() => {
    if (nativeRefreshPromiseRef.current) return nativeRefreshPromiseRef.current;

    const refreshPromise = (async () => {
      const current = sessionRef.current;
      if (!current || !nodeOrigin || current.nodeOrigin !== nodeOrigin) return null;
      const generation = generationRef.current;
      try {
        const response = await nativeRefresh(current.refreshToken);
        if (generationRef.current !== generation) return null;
        await applyResponse(response, nodeOrigin);
        return response.accessToken;
      } catch {
        // HTTP credentials do not own the separately provisioned board replica.
        if (generationRef.current !== generation) return null;
        setOfflineSession(true);
        return null;
      }
    })();

    nativeRefreshPromiseRef.current = refreshPromise;
    const clearRefresh = () => {
      if (nativeRefreshPromiseRef.current === refreshPromise) {
        nativeRefreshPromiseRef.current = null;
      }
    };
    void refreshPromise.then(clearRefresh, clearRefresh);
    return refreshPromise;
  }, [applyResponse, nodeOrigin]);

  useEffect(() => {
    setRefreshHandler(refreshCurrent);
    return () => setRefreshHandler(null);
  }, [refreshCurrent]);

  useEffect(() => {
    const generation = ++generationRef.current;
    setStatus('loading');
    setOfflineSession(false);

    if (!nodeOrigin) {
      applyStoredSession(null);
      return;
    }

    void (async () => {
      const stored = await loadStoredSession();
      if (generationRef.current !== generation) return;
      if (!stored || stored.nodeOrigin !== nodeOrigin) {
        applyStoredSession(null);
        return;
      }

      applyStoredSession(stored);
      if (!isOnline) {
        setOfflineSession(true);
        return;
      }

      try {
        if (expiredSoon(stored.accessTokenExpiresAt)) {
          await refreshCurrent();
          return;
        }
        const remote = await getSession();
        if (generationRef.current !== generation) return;
        if (!remote.authenticated || !remote.user) {
          await refreshCurrent();
        }
      } catch (error) {
        if (generationRef.current !== generation) return;
        if (error instanceof ApiError && error.status === 0) {
          setOfflineSession(true);
        } else {
          await refreshCurrent();
        }
      }
    })();
  }, [applyStoredSession, nodeOrigin, refreshCurrent]);

  useEffect(() => {
    if (!session) return;
    if (!isOnline) {
      setOfflineSession(true);
      return;
    }
    if (isOfflineSession) void refreshCurrent();
  }, [isOfflineSession, isOnline, refreshCurrent, session]);

  const prepareNewIdentity = useCallback(async (nextUserId: string) => {
    const previous = await loadStoredSession();
    if (previous && previous.user.id !== nextUserId) {
      await cancelAllCardReminders().catch(() => null);
      await clearSessionBoundStorage();
      queryClient.clear();
    }
  }, [queryClient]);

  const clearExplicitly = useCallback(async () => {
    ++generationRef.current;
    await cancelAllCardReminders().catch(() => null);
    await clearSessionBoundStorage();
    queryClient.clear();
    applyStoredSession(null);
    setOfflineSession(false);
  }, [applyStoredSession, queryClient]);

  const value = useMemo<AuthContextValue>(() => ({
    status,
    user: session?.user || null,
    sessionId: session?.sessionId || null,
    deviceId: session?.deviceId || null,
    isOfflineSession,
    signIn: async (input) => {
      if (!nodeOrigin) throw new Error('Узел не настроен.');
      const response = await nativeSignIn(input);
      await prepareNewIdentity(response.user.id);
      await applyResponse(response, nodeOrigin);
      queryClient.clear();
    },
    signUp: async (input) => {
      if (!nodeOrigin) throw new Error('Узел не настроен.');
      const response = await nativeSignUp(input);
      await prepareNewIdentity(response.user.id);
      await applyResponse(response, nodeOrigin);
      queryClient.clear();
    },
    signOut: async () => {
      try {
        if (nativeRefreshPromiseRef.current) await nativeRefreshPromiseRef.current;
        const current = sessionRef.current;
        if (current && isOnline) await nativeSignOut(current.refreshToken);
      } finally {
        await clearExplicitly();
      }
    },
    signOutEverywhere: async () => {
      try {
        if (nativeRefreshPromiseRef.current) await nativeRefreshPromiseRef.current;
        if (sessionRef.current && isOnline) await signOutAll();
      } finally {
        await clearExplicitly();
      }
    },
  }), [
    applyResponse,
    clearExplicitly,
    isOfflineSession,
    isOnline,
    nodeOrigin,
    prepareNewIdentity,
    queryClient,
    session,
    status,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
