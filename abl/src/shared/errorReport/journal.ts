// In-memory journal for error reports (contracts/error-report/1, «Кольцевой буфер»)
// and for the debug mode (abl/docs/DEBUG_MODE.md). Nothing leaves the WebView by
// itself: lines go into a report or a debug export, and those only into the
// clipboard, on a click. Nothing is stored: the frontend keeps no durable data
// outside the Rust repository boundary.
import type { ErrorReport } from './report';

/** Ordinary mode: enough for «Скопировать подробности». */
export const NORMAL_CAPACITY = 200;
/** Debug mode: a few minutes of busy sync, still well under a megabyte. */
export const DEBUG_CAPACITY = 5_000;

export type JournalLevel = 'debug' | 'info' | 'warn' | 'error';

export type JournalEntry = {
  seq: number;
  level: JournalLevel;
  source: string;
  /** `<UTC time> <level> <source>: <text>` — the form the contract recommends. */
  line: string;
};

let entries: JournalEntry[] = [];
let nextSeq = 1;
let debugMode = false;
const listeners = new Set<() => void>();

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

function capacity() {
  return debugMode ? DEBUG_CAPACITY : NORMAL_CAPACITY;
}

function push(level: JournalLevel, source: string, text: string) {
  const line = `${new Date().toISOString()} ${level} ${source}: ${text}`;
  entries.push({ seq: nextSeq++, level, source, line });
  if (entries.length > capacity()) entries.splice(0, entries.length - capacity());
  for (const listener of listeners) listener();
}

/** A line that is always kept: requests, warnings, errors, stalls. */
export function logLine(level: JournalLevel, source: string, ...parts: unknown[]) {
  push(level, source, parts.map(stringify).join(' '));
}

/**
 * A detailed line that only the debug mode keeps: sync steps, screens, network
 * changes. The text is built only when the mode is on, so ordinary use pays
 * nothing. Name ids, kinds and counts here, not card titles or descriptions.
 */
export function trace(source: string, describe: () => string) {
  if (!debugMode) return;
  let text: string;
  try { text = describe(); } catch (error) { text = `(строка не собрана: ${stringify(error)})`; }
  push('debug', source, text);
}

export function journalLines(): string[] {
  return entries.map((entry) => entry.line);
}

export function journalEntries(): JournalEntry[] {
  return [...entries];
}

/** Called on every new line; the viewer batches its own redraws. */
export function subscribeJournal(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function isJournalDebugMode() {
  return debugMode;
}

export function setJournalDebugMode(on: boolean) {
  debugMode = on;
  if (entries.length > capacity()) entries.splice(0, entries.length - capacity());
  for (const listener of listeners) listener();
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

export function resetJournalForTests() {
  entries = [];
  nextSeq = 1;
  debugMode = false;
  listeners.clear();
  lastFailure = null;
  platformNote = null;
}
