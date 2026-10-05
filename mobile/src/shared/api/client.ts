interface ApiEnvelope<T> {
  data: T;
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(message: string, input: { status: number; code?: string; details?: unknown }) {
    super(message);
    this.name = 'ApiError';
    this.status = input.status;
    this.code = input.code;
    this.details = input.details;
  }
}

let nodeOrigin: string | null = null;
let accessToken: string | null = null;
let refreshHandler: (() => Promise<string | null>) | null = null;
let refreshInFlight: Promise<string | null> | null = null;

export function setApiNodeOrigin(origin: string | null) {
  nodeOrigin = origin?.replace(/\/+$/, '') || null;
}

export function getApiNodeOrigin() {
  return nodeOrigin;
}

export function setAccessToken(token: string | null) {
  accessToken = token?.trim() || null;
}

export function getAccessToken() {
  return accessToken;
}

export function setRefreshHandler(handler: (() => Promise<string | null>) | null) {
  refreshHandler = handler;
}

async function parsePayload(response: Response) {
  const body = await response.text();
  if (!body) return null;
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return body;
  }
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Network request failed';
}

async function performRequest<T>(
  path: string,
  init: RequestInit,
  options: { skipRefresh: boolean; timeoutMs: number },
): Promise<T> {
  if (!nodeOrigin) {
    throw new ApiError('Сначала укажите адрес узла.', {
      status: 0,
      code: 'NODE_NOT_CONFIGURED',
    });
  }

  const headers = new Headers(init.headers);
  if (init.body !== undefined && init.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  headers.set('Accept', 'application/json');
  headers.set('X-p2pKanban-Client', 'android-native');
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);

  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, options.timeoutMs);
  const abort = () => controller.abort();
  if (init.signal?.aborted) abort();
  else init.signal?.addEventListener('abort', abort, { once: true });

  let response: Response;
  let payload: unknown;
  try {
    response = await fetch(`${nodeOrigin}/api/v1${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    // Reading the body is part of the request deadline too (RN may cancel here).
    payload = await parsePayload(response);
  } catch (error) {
    const aborted = controller.signal.aborted;
    throw new ApiError(
      timedOut ? 'Узел не ответил вовремя.' : aborted ? 'Запрос отменён вызывающим экраном.' : `Не удалось связаться с узлом: ${errorMessage(error)}.`,
      {
        status: 0,
        code: timedOut ? 'TIMEOUT' : aborted ? 'CANCELED' : 'NETWORK_ERROR',
        details: error,
      },
    );
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener('abort', abort);
  }

  if (response.status === 401 && !options.skipRefresh && refreshHandler) {
    refreshInFlight ??= refreshHandler().finally(() => {
      refreshInFlight = null;
    });
    const nextToken = await refreshInFlight;
    if (nextToken) {
      setAccessToken(nextToken);
      return performRequest<T>(path, init, { ...options, skipRefresh: true });
    }
  }

  if (!response.ok) {
    const apiError = (payload as ErrorEnvelope | null)?.error;
    throw new ApiError(apiError?.message || `Узел вернул HTTP ${response.status}.`, {
      status: response.status,
      code: apiError?.code,
      details: apiError?.details,
    });
  }

  if (payload && typeof payload === 'object' && 'data' in (payload as Record<string, unknown>)) {
    return (payload as ApiEnvelope<T>).data;
  }
  return payload as T;
}

export function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { skipRefresh?: boolean; timeoutMs?: number } = {},
) {
  return performRequest<T>(path, init, {
    skipRefresh: options.skipRefresh ?? false,
    timeoutMs: options.timeoutMs ?? 12_000,
  });
}

export function isNetworkError(error: unknown) {
  return error instanceof ApiError && error.status === 0;
}
