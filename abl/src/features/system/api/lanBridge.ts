import { apiRequest } from '../../../shared/api/client';
import type { LanBridgeStartResult, LanBridgeStatus } from '../../../shared/api/types';

export function listLanBridgeAddresses() {
  return apiRequest<string[]>('/system/lan-bridge/addresses');
}

export function getLanBridgeStatus() {
  return apiRequest<LanBridgeStatus>('/system/lan-bridge/status');
}

export function startLanBridge(bindAddress: string, ttlSeconds: number) {
  return apiRequest<LanBridgeStartResult>('/system/lan-bridge/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bindAddress, ttlSeconds }),
  });
}

export function stopLanBridge() {
  return apiRequest<LanBridgeStatus>('/system/lan-bridge/stop', { method: 'POST' });
}
