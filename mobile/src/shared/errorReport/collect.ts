// Gather everything a report needs at the moment the button is tapped.
import { Platform } from 'react-native';
import appJson from '../../../app.json';
import { ApiError } from '../api/client';
import { mobileClientVersion } from '../version';
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

/** Monorepo commit, inlined at bundle time by scripts/build-apk.mjs (or EAS). */
export function sourceRevision(): string | null {
  const value = process.env.EXPO_PUBLIC_SOURCE_REVISION?.trim();
  return value && /^[0-9a-f]{7,40}$/.test(value) ? value : null;
}

export function mobileSoftware(): ErrorReport['software'] {
  const code = appJson.expo.android?.versionCode;
  return { direction: 'mobile', version: mobileClientVersion, build: code ? String(code) : null, commit: sourceRevision() };
}

function platform(): string {
  const constants = Platform.constants as { Release?: string; Model?: string } | undefined;
  const release = constants?.Release ? `Android ${constants.Release}` : `${Platform.OS}`;
  return `${release} (API ${Platform.Version})${constants?.Model ? ` · ${constants.Model}` : ''}`;
}

function causeOf(error: unknown): unknown {
  return error && typeof error === 'object' ? (error as { cause?: unknown }).cause : undefined;
}

function apiErrorIn(error: unknown): ApiError | null {
  for (let current = error, depth = 0; current && depth < 5; current = causeOf(current), depth += 1) {
    if (current instanceof ApiError) return current;
  }
  return null;
}

function kindOf(error: unknown, api: ApiError | null): ErrorKind {
  if (api) return api.code === 'TIMEOUT' ? 'timeout' : api.status === 0 ? 'network' : 'http';
  if (error instanceof Error) return 'internal';
  return 'unknown';
}

export function collectReport(context: ReportContext): ErrorReport {
  const error = context.error;
  const api = apiErrorIn(error);
  const failure = api?.http
    ? { method: api.http.method, path: api.http.path, status: api.status, requestId: null, errorId: api.http.errorId, body: api.http.body, peer: peer() }
    : error === undefined ? recentApiFailure() : null;
  const http = failure ? { method: failure.method, path: failure.path, status: failure.status,
    requestId: failure.requestId, errorId: failure.errorId, body: failure.body } : null;
  const node = failure ? failure.peer : peer();
  const inner = api ?? (error instanceof Error ? error : null);
  return buildReport({
    reportId: newReportId(),
    at: new Date().toISOString(),
    software: mobileSoftware(),
    platform: platform(),
    screen: context.screen ?? null,
    operation: context.operation ?? null,
    stage: context.stage ?? null,
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
