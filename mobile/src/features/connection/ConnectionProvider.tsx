import type { PropsWithChildren } from 'react';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { setApiNodeOrigin } from '../../shared/api/client';
import {
  clearSessionBoundStorage,
  forgetNodeOrigin,
  loadKnownBackendVersion,
  loadNodeOrigin,
  saveKnownBackendVersion,
  saveNodeOrigin,
} from '../../shared/storage/storage';
import { normalizeNodeOrigin, probeNode } from './connection';

interface ConnectionContextValue {
  status: 'loading' | 'ready';
  nodeOrigin: string | null;
  backendVersion: string | null;
  connect: (input: string) => Promise<string>;
  disconnect: () => Promise<void>;
  rememberBackendVersion: (version: string) => Promise<void>;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<'loading' | 'ready'>('loading');
  const [nodeOrigin, setNodeOrigin] = useState<string | null>(null);
  const [backendVersion, setBackendVersion] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void loadNodeOrigin()
      .then(async (stored) => {
        if (!active) return;
        setApiNodeOrigin(stored);
        setNodeOrigin(stored);
        if (stored) {
          const knownVersion = await loadKnownBackendVersion(stored);
          if (active) setBackendVersion(knownVersion);
        }
      })
      .finally(() => {
        if (active) setStatus('ready');
      });
    return () => {
      active = false;
    };
  }, []);

  const value = useMemo<ConnectionContextValue>(
    () => ({
      status,
      nodeOrigin,
      backendVersion,
      connect: async (input) => {
        const normalized = normalizeNodeOrigin(input);
        const probedVersion = await probeNode(normalized);
        if (nodeOrigin && nodeOrigin !== normalized) {
          await clearSessionBoundStorage();
        }
        await saveNodeOrigin(normalized);
        if (probedVersion) await saveKnownBackendVersion(normalized, probedVersion);
        setApiNodeOrigin(normalized);
        setNodeOrigin(normalized);
        setBackendVersion(probedVersion || await loadKnownBackendVersion(normalized));
        return normalized;
      },
      disconnect: async () => {
        await clearSessionBoundStorage();
        await forgetNodeOrigin();
        setApiNodeOrigin(null);
        setNodeOrigin(null);
        setBackendVersion(null);
      },
      rememberBackendVersion: async (version) => {
        if (!nodeOrigin) return;
        await saveKnownBackendVersion(nodeOrigin, version);
        setBackendVersion(version);
      },
    }),
    [backendVersion, nodeOrigin, status],
  );

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}

export function useConnection() {
  const value = useContext(ConnectionContext);
  if (!value) throw new Error('useConnection must be used inside ConnectionProvider');
  return value;
}
