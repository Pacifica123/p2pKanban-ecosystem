import { ApiError } from '../api/errors';
import type { ApiTransport } from './types';

interface ApiEnvelope<T> { data: T }
interface ErrorEnvelope { error?: { code?: string; message?: string; details?: unknown } }

export function createWebHttpTransport(apiBaseUrl: string, fetchImpl: typeof fetch = fetch): ApiTransport {
  const base = apiBaseUrl.replace(/\/+$/, '');
  return {
    kind: 'web',
    async request<T>(path: string, init: RequestInit = {}) {
      let response: Response;
      try {
        response = await fetchImpl(`${base}${path}`, { ...init, credentials: 'include' });
      } catch (error) {
        throw new ApiError('Web backend is unreachable.', { status: 0, code: 'NETWORK_ERROR', details: error });
      }
      const text = await response.text();
      let payload: unknown = null;
      if (text) {
        try { payload = JSON.parse(text) as unknown; } catch { payload = text; }
      }
      if (!response.ok) {
        const apiError = (payload as ErrorEnvelope | null)?.error;
        throw new ApiError(apiError?.message ?? `Request failed with ${response.status}`, {
          status: response.status,
          code: apiError?.code,
          details: apiError?.details,
        });
      }
      if (payload && typeof payload === 'object' && 'data' in (payload as Record<string, unknown>)) {
        return (payload as ApiEnvelope<T>).data;
      }
      return payload as T;
    },
  };
}
