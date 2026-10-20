// «Режим отладки» (docs/architecture/debug-mode-20261017.md): a switch in Settings that makes the
// journal record every sync step, screen and network change and keep 5 000 lines
// instead of 200. Off by default: it costs a little CPU, which a person opts into.
// The redacted tail on disk is kept by the black box in every mode
// (docs/architecture/stall-watch-20261020.md); the debug mode makes it longer.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSyncExternalStore } from 'react';
import { AppState } from 'react-native';

import {
  isJournalDebugMode,
  logLine,
  setJournalDebugMode,
  subscribeJournal,
} from '../errorReport/journal';
import { BOX_DEBUG_LINES, previousRunLines } from '../lib/stallWatch';

const MODE_KEY = '@p2pkanban/mobile/v1/diagnostics/debug-mode';
/** Lines kept on disk for the next start while the mode is on. */
export const TAIL_LINES = BOX_DEBUG_LINES;

let installed = false;

/** Read the switch; log app state changes. */
export async function installDebugMode() {
  if (installed) return;
  installed = true;
  AppState.addEventListener('change', (state) => logLine('info', 'app', `состояние приложения: ${state}`));
  try {
    const mode = await AsyncStorage.getItem(MODE_KEY);
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
  }
  try {
    if (on) await AsyncStorage.setItem(MODE_KEY, '1');
    else await AsyncStorage.removeItem(MODE_KEY);
  } catch {
    logLine('warn', 'debug', 'не удалось сохранить переключатель режима отладки');
  }
}

/** The redacted tail the black box kept from the previous run, old first. */
export { previousRunLines };

export function useDebugMode() {
  return useSyncExternalStore(subscribeJournal, isJournalDebugMode);
}
