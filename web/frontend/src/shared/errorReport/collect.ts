// Gather everything a report needs at the moment the button is pressed.
import { ApiError } from '@/shared/api/errors';
import { webClientVersion } from '@/shared/version';
import { journalLines, peer, recentApiFailure } from './journal';
import { buildReport, newReportId, type ErrorKind, type ErrorReport } from './report';

export type ReportContext = {
  /** What the person saw. */
  message: string;
  error?: unknown;
  screen?: string;
  operation?: string;
  stage?: string;
};

const known = (value: string | undefined) => {
  const text = value?.trim();
  return text && text !== 'unknown' ? text : null;
};

export function webSoftware(): ErrorReport['software'] {
  const env = import.meta.env as Record<string, string | undefined>;
  return { direction: 'web', version: webClientVersion, build: known(env.VITE_BUILD_ID), commit: known(env.VITE_SOURCE_REVISION) };
}

function causeOf(error: unknown): unknown {
  if (error && typeof error === 'object') {
    const holder = error as { originalCause?: unknown; cause?: unknown };
    return holder.originalCause ?? holder.cause;
  }
  return undefined;
}

/** The innermost ApiError, if the error chain has one. */
function apiErrorIn(error: unknown): ApiError | null {
  for (let current = error, depth = 0; current && depth < 5; current = causeOf(current), depth += 1) {
    if (current instanceof ApiError) return current;
  }
  return null;
}

function kindOf(error: unknown, api: ApiError | null): ErrorKind {
  if (api) return api.status === 0 ? 'network' : 'http';
  if (error instanceof DOMException && error.name === 'TimeoutError') return 'timeout';
  if (error instanceof DOMException && error.name === 'QuotaExceededError') return 'storage';
  if (error instanceof Error) return 'internal';
  return 'unknown';
}

export function collectReport(context: ReportContext): ErrorReport {
  const api = apiErrorIn(context.error);
  const failure = api?.http
    ? { method: api.http.method, path: api.http.path, status: api.status, requestId: null, errorId: api.http.errorId, body: api.http.body }
    : context.error === undefined ? recentApiFailure() : null;
  const http = failure ? { method: failure.method, path: failure.path, status: failure.status,
    requestId: failure.requestId, errorId: failure.errorId, body: failure.body } : null;
  const node = failure && 'peer' in failure ? failure.peer : peer();
  const error = context.error;
  const stage = context.stage ?? (error && typeof error === 'object' && typeof (error as { stage?: unknown }).stage === 'string'
    ? (error as { stage: string }).stage : undefined);
  const inner = api ?? (error instanceof Error ? error : null);
  return buildReport({
    reportId: newReportId(),
    at: new Date().toISOString(),
    software: webSoftware(),
    platform: typeof navigator === 'undefined' ? null : navigator.userAgent,
    screen: context.screen ?? (typeof document === 'undefined' ? null : document.title || null),
    operation: context.operation ?? null,
    stage: stage ?? null,
    message: context.message,
    error: {
      kind: error === undefined && http ? (http.status ? 'http' : 'network') : kindOf(error, api),
      name: inner?.name ?? (error === undefined ? null : typeof error),
      detail: inner?.message ?? (error === undefined || error === null ? null : String(error)),
    },
    http,
    peer: node ? { direction: 'web', ...node } : null,
    logs: journalLines(),
  });
}
