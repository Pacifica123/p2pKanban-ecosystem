import NetInfo from '@react-native-community/netinfo';
import { onlineManager } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

interface NetworkContextValue {
  isOnline: boolean;
  networkType: string;
}

const NetworkContext = createContext<NetworkContextValue>({
  isOnline: true,
  networkType: 'unknown',
});

function connected(value: { isConnected: boolean | null; isInternetReachable: boolean | null }) {
  // Internet probes do not determine LAN or relay reachability.
  return value.isConnected !== false;
}

export function NetworkProvider({ children }: PropsWithChildren) {
  const [isOnline, setOnline] = useState(true);
  const [networkType, setNetworkType] = useState('unknown');

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      const next = connected(state);
      setOnline(next);
      setNetworkType(state.type);
      onlineManager.setOnline(next);
    });
    void NetInfo.fetch().then((state) => {
      const next = connected(state);
      setOnline(next);
      setNetworkType(state.type);
      onlineManager.setOnline(next);
    });
    return unsubscribe;
  }, []);

  const value = useMemo(() => ({ isOnline, networkType }), [isOnline, networkType]);
  return <NetworkContext.Provider value={value}>{children}</NetworkContext.Provider>;
}

export function useNetwork() {
  return useContext(NetworkContext);
}
