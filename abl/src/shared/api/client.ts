import type { ApiTransport } from '../transport/types';
import { desktopTransport } from '../transport/desktop';
import { requestMethod } from '../transport/types';
import { logLine, noteFailure } from '../errorReport/journal';
import { ApiError } from './errors';

let activeTransport: ApiTransport = desktopTransport;

export function setApiTransport(transport: ApiTransport): void {
  activeTransport = transport;
}

export function getApiTransportKind(): ApiTransport['kind'] {
  return activeTransport.kind;
}

/** Native commands reject with a bare code string; keep the code and the route in the error. */
function described(error: unknown, method: string, path: string): unknown {
  if (typeof error !== 'string') return error;
  return new ApiError(`Нативная операция ${method} ${path} не удалась: ${error}`, { status: 0, code: 'NATIVE_ERROR', details: error });
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = requestMethod(init);
  try {
    const value = await activeTransport.request<T>(path, init);
    logLine('debug', activeTransport.kind, `${method} ${path} → ok`);
    return value;
  } catch (reason) {
    const error = described(reason, method, path);
    logLine('error', activeTransport.kind, `${method} ${path} →`, error);
    const http = error instanceof ApiError && activeTransport.kind === 'web'
      ? { method, path, status: error.status, requestId: null, errorId: null, body: null }
      : null;
    noteFailure({ method, path, error, http });
    throw error;
  }
}
