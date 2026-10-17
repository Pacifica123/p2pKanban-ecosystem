// In-memory journal for error reports (contracts/error-report/1, «Кольцевой буфер»)
// and for the debug mode (docs/architecture/debug-mode-20261017.md). Nothing leaves the phone by
// itself: lines go into a report or a debug export, and those only into the
// clipboard or a share sheet, on a tap. Only the debug mode keeps a redacted
// tail on disk, so the next start can show how the previous run ended.
import { NODE_HEADER, parseNodeHeader, type ErrorReport, type NodeIdentity } from './report';

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

export type ApiFailure = NonNullable<ErrorReport['http']> & { at: number; peer: NodeIdentity | null };

let lastPeer: NodeIdentity | null = null;
let lastFailure: ApiFailure | null = null;

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

/** Remember which node answered last (`x-p2p-kanban-node`); an old node sends none. */
export function notePeer(headers: { get(name: string): string | null } | null | undefined) {
  const value = headers?.get?.(NODE_HEADER);
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

type GlobalHandler = (error: unknown, isFatal?: boolean) => void;
let installed = false;

/** Mirror console warnings/errors and uncaught JS errors into the journal. */
export function installJournal() {
  if (installed) return;
  installed = true;
  for (const level of ['warn', 'error'] as const) {
    const original = console[level].bind(console);
    console[level] = (...args: unknown[]) => {
      logLine(level, 'console', ...args);
      original(...args);
    };
  }
  const utils = (globalThis as { ErrorUtils?: { getGlobalHandler(): GlobalHandler; setGlobalHandler(h: GlobalHandler): void } }).ErrorUtils;
  if (utils) {
    const previous = utils.getGlobalHandler();
    utils.setGlobalHandler((error, isFatal) => {
      logLine('error', isFatal ? 'fatal' : 'js', error);
      previous(error, isFatal);
    });
  }
}

export function resetJournalForTests() {
  entries = [];
  nextSeq = 1;
  debugMode = false;
  listeners.clear();
  lastPeer = null;
  lastFailure = null;
}
