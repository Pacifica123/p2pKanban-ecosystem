// In-memory journal for error reports (contracts/error-report/1, «Кольцевой буфер»).
// Nothing is written to disk and nothing leaves the browser by itself: lines
// only go into a report, and a report only into the clipboard, on a click.
import { NODE_HEADER, parseNodeHeader, type ErrorReport, type NodeIdentity } from './report';

const CAPACITY = 200;
const lines: string[] = [];

export type ApiFailure = NonNullable<ErrorReport['http']> & { at: number; peer: NodeIdentity | null };

let lastPeer: NodeIdentity | null = null;
let lastFailure: ApiFailure | null = null;

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

/** Remember which node answered last (from `x-p2p-kanban-node`); an old node sends none. */
export function notePeer(headers: Headers | null | undefined) {
  const value = headers?.get(NODE_HEADER);
  if (value) lastPeer = parseNodeHeader(value);
}

export function peer(): NodeIdentity | null {
  return lastPeer;
}

export function noteApiFailure(failure: Omit<ApiFailure, 'at' | 'peer'>) {
  lastFailure = { ...failure, at: Date.now(), peer: lastPeer };
}

/** The last failed request, if it is recent enough to explain what is on screen. */
export function recentApiFailure(maxAgeMs = 120_000): ApiFailure | null {
  return lastFailure && Date.now() - lastFailure.at <= maxAgeMs ? lastFailure : null;
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

export function resetJournalForTests() {
  lines.length = 0;
  lastPeer = null;
  lastFailure = null;
}
