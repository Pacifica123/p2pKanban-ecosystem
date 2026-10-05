import type { ApiTransport } from '../transport/types';
import { desktopTransport } from '../transport/desktop';

let activeTransport: ApiTransport = desktopTransport;

export function setApiTransport(transport: ApiTransport): void {
  activeTransport = transport;
}

export function getApiTransportKind(): ApiTransport['kind'] {
  return activeTransport.kind;
}

export function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  return activeTransport.request<T>(path, init);
}
