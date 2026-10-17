// «Режим отладки» (docs/architecture/debug-mode-20261017.md): a switch in Settings that makes the
// journal record every sync step, screen and network change, keeps 5 000 lines
// instead of 200 and saves a redacted tail every few seconds, so a run that
// ended in a freeze or a kill can be read after the restart. Off by default:
// it costs a little CPU and storage, which a person opts into.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSyncExternalStore } from 'react';
import { AppState } from 'react-native';

import {
  isJournalDebugMode,
  journalLines,
  logLine,
  setJournalDebugMode,
  subscribeJournal,
} from '../errorReport/journal';
import { redactLines } from './export';

const MODE_KEY = '@p2pkanban/mobile/v1/diagnostics/debug-mode';
const TAIL_KEY = '@p2pkanban/mobile/v1/diagnostics/debug-tail';
/** Lines kept on disk for the next start. */
export const TAIL_LINES = 500;
const PERSIST_EVERY_MS = 3_000;

let previousRun: string[] = [];
let persistTimer: ReturnType<typeof setTimeout> | null = null;
let installed = false;

function persistSoon() {
  if (!isJournalDebugMode() || persistTimer) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    if (!isJournalDebugMode()) return;
    const [tail] = redactLines(journalLines().slice(-TAIL_LINES));
    void AsyncStorage.setItem(TAIL_KEY, JSON.stringify(tail)).catch(() => undefined);
  }, PERSIST_EVERY_MS);
}

/** Read the switch and the previous run's tail; log app state changes. */
export async function installDebugMode() {
  if (installed) return;
  installed = true;
  subscribeJournal(persistSoon);
  AppState.addEventListener('change', (state) => logLine('info', 'app', `состояние приложения: ${state}`));
  try {
    const [mode, tail] = await Promise.all([AsyncStorage.getItem(MODE_KEY), AsyncStorage.getItem(TAIL_KEY)]);
    if (tail) {
      const parsed = JSON.parse(tail) as unknown;
      if (Array.isArray(parsed)) previousRun = parsed.filter((line): line is string => typeof line === 'string');
    }
    if (mode === '1') {
      setJournalDebugMode(true);
      logLine('info', 'debug', 'режим отладки включён (с прошлого запуска)');
    }
  } catch {
    // An unreadable setting leaves the mode off; the app works as before.
  }
}

export async function setDebugMode(on: boolean) {
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
    if (on) await AsyncStorage.setItem(MODE_KEY, '1');
    else await Promise.all([AsyncStorage.removeItem(MODE_KEY), AsyncStorage.removeItem(TAIL_KEY)]);
  } catch {
    logLine('warn', 'debug', 'не удалось сохранить переключатель режима отладки');
  }
}

/** The redacted tail the debug mode saved during the previous run, old first. */
export function previousRunLines() {
  return previousRun;
}

export function useDebugMode() {
  return useSyncExternalStore(subscribeJournal, isJournalDebugMode);
}
