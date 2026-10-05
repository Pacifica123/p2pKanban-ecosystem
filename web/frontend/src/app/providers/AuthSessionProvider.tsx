import type { PropsWithChildren } from 'react';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
  setAuthLifecycleHandlers,
} from '@/shared/api/client';
import { importAccountFromNode, refreshSession, signIn, signOut, signOutAll, signUp } from '@/features/auth/api/auth';
import type { AuthSuccessResponse, AuthUser, NodeLinkImportRequest, SignInRequest, SignUpRequest } from '@/shared/types/api';

interface AuthSessionContextValue {
  status: 'loading' | 'authenticated' | 'anonymous';
  user: AuthUser | null;
  sessionId: string | null;
  deviceId: string | null;
  signInWithPassword: (input: SignInRequest) => Promise<void>;
  signUpWithPassword: (input: SignUpRequest) => Promise<void>;
  signInFromAnotherNode: (input: NodeLinkImportRequest) => Promise<void>;
  signOutCurrent: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
  refreshCurrentSession: () => Promise<void>;
}

const AuthSessionContext = createContext<AuthSessionContextValue | undefined>(undefined);

function toUserState(response: AuthSuccessResponse) {
  return {
    status: 'authenticated' as const,
    user: response.user,
    sessionId: response.sessionId,
    deviceId: response.deviceId,
  };
}

export function AuthSessionProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<'loading' | 'authenticated' | 'anonymous'>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const authActionGenerationRef = useRef(0);

  const clearLocalSession = useCallback(() => {
    clearAccessToken();
    setStatus('anonymous');
    setUser(null);
    setSessionId(null);
    setDeviceId(null);
    queryClient.clear();
  }, [queryClient]);

  const applyAuthResponse = useCallback((response: AuthSuccessResponse) => {
    const next = toUserState(response);
    setAccessToken(response.accessToken);
    setStatus(next.status);
    setUser(next.user);
    setSessionId(next.sessionId);
    setDeviceId(next.deviceId);
  }, []);

  useEffect(() => {
    let active = true;
    setAuthLifecycleHandlers({
      refresh: async () => {
        const generation = authActionGenerationRef.current;
        const response = await refreshSession();
        if (!active || authActionGenerationRef.current !== generation) {
          return getAccessToken();
        }
        applyAuthResponse(response);
        return response.accessToken;
      },
      expired: clearLocalSession,
    });
    return () => {
      active = false;
      setAuthLifecycleHandlers({ refresh: null, expired: null });
    };
  }, [applyAuthResponse, clearLocalSession]);

  useEffect(() => {
    let cancelled = false;
    const bootstrapGeneration = authActionGenerationRef.current;

    void refreshSession()
      .then((response) => {
        if (cancelled || authActionGenerationRef.current !== bootstrapGeneration) return;
        applyAuthResponse(response);
      })
      .catch(() => {
        if (!cancelled && authActionGenerationRef.current === bootstrapGeneration) {
          clearLocalSession();
        }
      });

    return () => {
      cancelled = true;
    };
  }, [applyAuthResponse, clearLocalSession]);

  const value = useMemo<AuthSessionContextValue>(
    () => ({
      status,
      user,
      sessionId,
      deviceId,
      signInWithPassword: async (input) => {
        const actionGeneration = ++authActionGenerationRef.current;
        try {
          const response = await signIn(input);
          if (authActionGenerationRef.current === actionGeneration) {
            applyAuthResponse(response);
          }
        } catch (error) {
          if (authActionGenerationRef.current === actionGeneration) {
            clearLocalSession();
          }
          throw error;
        }
      },
      signUpWithPassword: async (input) => {
        const actionGeneration = ++authActionGenerationRef.current;
        try {
          const response = await signUp(input);
          if (authActionGenerationRef.current === actionGeneration) {
            applyAuthResponse(response);
          }
        } catch (error) {
          if (authActionGenerationRef.current === actionGeneration) {
            clearLocalSession();
          }
          throw error;
        }
      },
      signInFromAnotherNode: async (input) => {
        const actionGeneration = ++authActionGenerationRef.current;
        try {
          const response = await importAccountFromNode(input);
          if (authActionGenerationRef.current === actionGeneration) {
            applyAuthResponse(response);
          }
        } catch (error) {
          if (authActionGenerationRef.current === actionGeneration) {
            clearLocalSession();
          }
          throw error;
        }
      },
      signOutCurrent: async () => {
        ++authActionGenerationRef.current;
        try {
          await signOut();
        } finally {
          clearLocalSession();
        }
      },
      signOutEverywhere: async () => {
        ++authActionGenerationRef.current;
        try {
          await signOutAll();
        } finally {
          clearLocalSession();
        }
      },
      refreshCurrentSession: async () => {
        const actionGeneration = ++authActionGenerationRef.current;
        try {
          const response = await refreshSession();
          if (authActionGenerationRef.current === actionGeneration) {
            applyAuthResponse(response);
          }
        } catch (error) {
          if (authActionGenerationRef.current === actionGeneration) {
            clearLocalSession();
          }
          throw error;
        }
      },
    }),
    [applyAuthResponse, clearLocalSession, deviceId, sessionId, status, user],
  );

  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

export function useAuthSession() {
  const context = useContext(AuthSessionContext);
  if (!context) throw new Error('useAuthSession must be used inside AuthSessionProvider');
  return context;
}
