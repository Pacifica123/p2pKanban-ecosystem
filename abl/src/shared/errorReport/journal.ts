// In-memory journal for error reports (contracts/error-report/1, «Кольцевой буфер»).
// Nothing is written to disk and nothing leaves the WebView by itself: lines
// only go into a report, and a report only into the clipboard, on a click.
import type { ErrorReport } from './report';

const CAPACITY = 200;
const lines: string[] = [];

export type Failure = {
  at: number;
  method: string;
  path: string;
  error: unknown;
  /** Only for the web transport: what the node answered. */
  http: ErrorReport['http'];
};

let lastFailure: Failure | null = null;
let platformNote: string | null = null;

function stringify(value: unknown): string {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch { return String(value); }
}

/** `<UTC time> <level> <source>: <text>` — the form the contract recommends. */
export function logLine(level: 'debug' | 'info' | 'warn' | 'error', source: string, ...parts: unknown[]) {
  lines.push(`${new Date().toISOString()} ${level} ${source}: ${parts.map(stringify).join(' ')}`);
  if (lines.length > CAPACITY) lines.splice(0, lines.length - CAPACITY);
}

export function journalLines(): string[] {
  return [...lines];
}

export function noteFailure(failure: Omit<Failure, 'at'>) {
  lastFailure = { ...failure, at: Date.now() };
}

/** The last failed native command or request, if recent enough to explain the banner. */
export function recentFailure(maxAgeMs = 120_000): Failure | null {
  return lastFailure && Date.now() - lastFailure.at <= maxAgeMs ? lastFailure : null;
}

/** Desktop session facts (desktop, session type) to append to the WebKitGTK user agent. */
export function notePlatform(text: string | null) {
  platformNote = text;
}

export function platformText(): string {
  const agent = typeof navigator === 'undefined' ? '' : navigator.userAgent;
  return [platformNote, agent].filter(Boolean).join(' · ');
}

let installed = false;

/** Mirror console warnings/errors and uncaught errors into the journal. */
export function installJournal(target: Window & typeof globalThis = window) {
  if (installed) return;
  installed = true;
  for (const level of ['warn', 'error'] as const) {
    const original = target.console[level].bind(target.console);
    target.console[level] = (...args: unknown[]) => {
      logLine(level, 'console', ...args);
      original(...args);
    };
  }
  target.addEventListener('error', (event) => logLine('error', 'window', event.message || event.error));
  target.addEventListener('unhandledrejection', (event) => logLine('error', 'promise', event.reason));
}
