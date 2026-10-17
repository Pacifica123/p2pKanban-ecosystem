// «Режим отладки» (abl/docs/DEBUG_MODE.md): a switch in the «Журнал отладки»
// panel that makes the journal record section changes and other detailed
// lines and keep 5 000 lines instead of 200. Off at every start: the frontend
// keeps nothing durable outside the Rust repository boundary (A07–A09), so
// neither the switch nor a tail of the journal is stored. A tail across
// restarts would need a native command that writes it into the profile.
import { useSyncExternalStore } from 'react';
import { isJournalDebugMode, logLine, setJournalDebugMode, subscribeJournal } from '../errorReport/journal';

let installed = false;

/** Log network and window visibility changes; they explain most sync surprises. */
export function installDebugMode(target: Window & typeof globalThis = window) {
  if (installed) return;
  installed = true;
  target.addEventListener('online', () => logLine('info', 'net', 'сеть: есть подключение'));
  target.addEventListener('offline', () => logLine('info', 'net', 'сеть: нет подключения'));
  target.document.addEventListener('visibilitychange', () =>
    logLine('info', 'app', `окно ${target.document.visibilityState === 'visible' ? 'на экране' : 'скрыто'}`));
}

export function setDebugMode(on: boolean) {
  if (on === isJournalDebugMode()) return;
  if (on) {
    setJournalDebugMode(true);
    logLine('info', 'debug', 'режим отладки включён');
  } else {
    logLine('info', 'debug', 'режим отладки выключен');
    setJournalDebugMode(false);
  }
}

/** abl keeps no tail between runs; the panel shows only this run. */
export function previousRunLines(): string[] {
  return [];
}

export function useDebugMode() {
  return useSyncExternalStore(subscribeJournal, isJournalDebugMode);
}
