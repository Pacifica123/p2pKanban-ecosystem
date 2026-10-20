import { logLine, noteApiFailure, notePeer, trace } from '../errorReport/journal';
import { ERROR_ID_HEADER } from '../errorReport/report';
import { nodeBlock, noteNodeAnswered, noteNodeSilent, resetNodeReach } from './nodeReach';

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

export interface ApiErrorHttp {
  method: string;
  path: string;
  /** Raw response text (redacted only when a report is built). */
  body: string | null;
  /** `errorId` of a 5xx answered by the node (contracts/error-report/1). */
  errorId: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;
  readonly http?: ApiErrorHttp;

  constructor(message: string, input: { status: number; code?: string; details?: unknown; http?: ApiErrorHttp }) {
    super(message);
    this.name = 'ApiError';
    this.status = input.status;
    this.code = input.code;
    this.details = input.details;
    this.http = input.http;
  }
}

let nodeOrigin: string | null = null;
let accessToken: string | null = null;
let refreshHandler: (() => Promise<string | null>) | null = null;
let refreshInFlight: Promise<string | null> | null = null;

export function setApiNodeOrigin(origin: string | null) {
  nodeOrigin = origin?.replace(/\/+$/, '') || null;
  resetNodeReach();
}

type InFlight = { method: string; path: string; startedAt: number };
const inFlight = new Map<number, InFlight>();
let nextRequestId = 1;

/** Requests to the node that have not settled yet, oldest first (for the stall watch). */
export function inFlightRequests(now = Date.now()) {
  return [...inFlight.values()].map((item) => ({ method: item.method, path: item.path, ageMs: now - item.startedAt }));
}

let lastBlockReason: string | null = null;

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
  if (!body) return { text: body, payload: null as unknown };
  try {
    return { text: body, payload: JSON.parse(body) as unknown };
  } catch {
    return { text: body, payload: body as unknown };
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

  const method = (init.method ?? 'GET').toUpperCase();
  const requestPath = `/api/v1${path}`;
  const block = nodeBlock(nodeOrigin);
  if (block) {
    // One line per reason, not per request: a board screen asks every few seconds.
    if (block.reason !== lastBlockReason) {
      lastBlockReason = block.reason;
      logLine('info', 'api', `${nodeOrigin}: запросы к узлу не отправляются — ${block.message}`);
    }
    trace('api', () => `${method} ${requestPath} → не отправлен: ${block.message}`);
    throw new ApiError(block.message, {
      status: 0,
      code: 'NODE_UNREACHABLE',
      http: { method, path: requestPath, body: null, errorId: null },
    });
  }
  lastBlockReason = null;

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

  const startedAt = Date.now();
  const requestId = nextRequestId++;
  inFlight.set(requestId, { method, path: requestPath, startedAt });
  let response: Response;
  let payload: unknown;
  let text = '';
  let answered = false;
  try {
    response = await fetch(`${nodeOrigin}/api/v1${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    answered = true;
    if (noteNodeAnswered()) logLine('info', 'api', `${nodeOrigin}: узел снова отвечает`);
    // Reading the body is part of the request deadline too (RN may cancel here).
    ({ text, payload } = await parsePayload(response));
  } catch (error) {
    const aborted = controller.signal.aborted;
    const code = timedOut ? 'TIMEOUT' : aborted ? 'CANCELED' : 'NETWORK_ERROR';
    if (code !== 'CANCELED') {
      logLine('error', 'api', `${method} ${nodeOrigin}${requestPath} → нет ответа (${code}): ${errorMessage(error)}`);
      noteApiFailure({ method, path: requestPath, status: 0, requestId: null, errorId: null, body: null });
      // Headers came but the body did not: the node is there, only slow.
      const pause = answered ? 0 : noteNodeSilent();
      if (pause) logLine('warn', 'api', `${nodeOrigin}: узел молчит, следующие ${Math.round(pause / 1000)} с запросы к нему не отправляются`);
    }
    throw new ApiError(
      timedOut ? 'Узел не ответил вовремя.' : aborted ? 'Запрос отменён вызывающим экраном.' : `Не удалось связаться с узлом: ${errorMessage(error)}.`,
      {
        status: 0,
        code,
        details: error,
        http: { method, path: requestPath, body: null, errorId: null },
      },
    );
  } finally {
    inFlight.delete(requestId);
    clearTimeout(timeout);
    init.signal?.removeEventListener('abort', abort);
  }

  notePeer(response.headers);
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
    const errorId = response.headers?.get?.(ERROR_ID_HEADER) ?? null;
    logLine(response.status >= 500 ? 'error' : 'warn', 'api',
      `${method} ${nodeOrigin}${requestPath} → ${response.status}${errorId ? ` (ошибка узла ${errorId})` : ''}`);
    noteApiFailure({ method, path: requestPath, status: response.status, requestId: null, errorId, body: text || null });
    throw new ApiError(apiError?.message || `Узел вернул HTTP ${response.status}.`, {
      status: response.status,
      code: apiError?.code,
      details: apiError?.details,
      http: { method, path: requestPath, body: text || null, errorId },
    });
  }
  logLine('debug', 'api', `${method} ${requestPath} → ${response.status} за ${Date.now() - startedAt} мс`);

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
