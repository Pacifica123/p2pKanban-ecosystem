// Gather everything a report needs at the moment the button is pressed.
import packageJson from '../../../package.json';
import { ApiError } from '../api/errors';
import { journalLines, platformText, recentFailure } from './journal';
import { buildReport, newReportId, type ErrorKind, type ErrorReport } from './report';

declare const __ABL_BUILD__: string | null;
declare const __ABL_SOURCE_REVISION__: string | null;

export function ablSoftware(): ErrorReport['software'] {
  return {
    direction: 'abl',
    version: packageJson.version,
    build: typeof __ABL_BUILD__ === 'string' ? __ABL_BUILD__ : null,
    commit: typeof __ABL_SOURCE_REVISION__ === 'string' ? __ABL_SOURCE_REVISION__ : null,
  };
}

function kindOf(error: unknown): ErrorKind {
  if (error instanceof ApiError) {
    if (error.code === 'NATIVE_ERROR') return 'native';
    return error.status === 0 ? 'network' : 'http';
  }
  if (typeof error === 'string') return 'native';
  if (error instanceof Error) return 'internal';
  return 'unknown';
}

export function collectReport(context: { message: string; error?: unknown; operation?: string; stage?: string }): ErrorReport {
  const failure = recentFailure();
  const error = context.error ?? failure?.error;
  const inner = error instanceof Error ? error : null;
  const operation = context.operation ?? (failure ? `${failure.method} ${failure.path}` : null);
  return buildReport({
    reportId: newReportId(),
    at: new Date().toISOString(),
    software: ablSoftware(),
    platform: platformText() || null,
    screen: typeof document === 'undefined' ? null : document.title || null,
    operation,
    stage: context.stage ?? null,
    message: context.message,
    error: {
      kind: error === undefined ? 'unknown' : kindOf(error),
      name: inner instanceof ApiError ? inner.code ?? inner.name : inner?.name ?? (error === undefined ? null : typeof error),
      detail: inner?.message ?? (error === undefined || error === null ? null : String(error)),
    },
    http: failure?.http ?? null,
    peer: null,
    logs: journalLines(),
  });
}
