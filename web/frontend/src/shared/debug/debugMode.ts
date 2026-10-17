// «Режим отладки» (docs/architecture/debug-mode-20261017.md): a switch in the
// «Журнал отладки» page that makes the journal record page changes and other
// detailed lines, keeps 5 000 lines instead of 200 and saves a redacted tail
// every few seconds, so a reload after a hang still shows how the page ended.
// Off by default. The switch lives in this browser only.
import { useSyncExternalStore } from 'react';
import {
  isJournalDebugMode,
  journalLines,
  logLine,
  setJournalDebugMode,
  subscribeJournal,
} from '@/shared/errorReport/journal';
import { redactLines } from './export';

const MODE_KEY = 'p2pkanban:debug-mode';
const TAIL_KEY = 'p2pkanban:debug-tail';
/** Lines kept in localStorage for the next page load. */
export const TAIL_LINES = 500;
const PERSIST_EVERY_MS = 3_000;

let previousRun: string[] = [];
let persistTimer: ReturnType<typeof setTimeout> | null = null;
let installed = false;

function storage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}

function persistSoon() {
  if (!isJournalDebugMode() || persistTimer) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    if (!isJournalDebugMode()) return;
    const [tail] = redactLines(journalLines().slice(-TAIL_LINES));
    try { storage()?.setItem(TAIL_KEY, JSON.stringify(tail)); } catch { /* full storage: the tail is optional */ }
  }, PERSIST_EVERY_MS);
}

/** Read the switch and the previous page's tail; log network and tab visibility. */
export function installDebugMode(target: Window & typeof globalThis = window) {
  if (installed) return;
  installed = true;
  subscribeJournal(persistSoon);
  target.addEventListener('online', () => logLine('info', 'net', 'браузер: сеть есть'));
  target.addEventListener('offline', () => logLine('info', 'net', 'браузер: сети нет'));
  target.document.addEventListener('visibilitychange', () =>
    logLine('info', 'app', `вкладка ${target.document.visibilityState === 'visible' ? 'на экране' : 'скрыта'}`));
  try {
    const tail = storage()?.getItem(TAIL_KEY);
    if (tail) {
      const parsed = JSON.parse(tail) as unknown;
      if (Array.isArray(parsed)) previousRun = parsed.filter((line): line is string => typeof line === 'string');
    }
    if (storage()?.getItem(MODE_KEY) === '1') {
      setJournalDebugMode(true);
      logLine('info', 'debug', 'режим отладки включён (с прошлой загрузки страницы)');
    }
  } catch {
    // An unreadable setting leaves the mode off; the page works as before.
  }
}

export function setDebugMode(on: boolean) {
  if (on === isJournalDebugMode()) return;
  if (on) {
    setJournalDebugMode(true);
    logLine('info', 'debug', 'режим отладки включён');
  } else {
    logLine('info', 'debug', 'режим отладки выключен');
    setJournalDebugMode(false);
    if (persistTimer) { clearTimeout(persistTimer); persistTimer = null; }
  }
  try {
    if (on) storage()?.setItem(MODE_KEY, '1');
    else { storage()?.removeItem(MODE_KEY); storage()?.removeItem(TAIL_KEY); }
  } catch {
    logLine('warn', 'debug', 'не удалось сохранить переключатель режима отладки');
  }
}

/** The redacted tail the debug mode saved before the last reload, old first. */
export function previousRunLines() {
  return previousRun;
}

export function useDebugMode() {
  return useSyncExternalStore(subscribeJournal, isJournalDebugMode);
}

export function resetDebugModeForTests() {
  previousRun = [];
  installed = false;
  if (persistTimer) { clearTimeout(persistTimer); persistTimer = null; }
}
