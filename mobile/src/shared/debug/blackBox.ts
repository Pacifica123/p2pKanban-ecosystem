// «Чёрный ящик» (docs/architecture/stall-watch-20261020.md): what the app was
// doing, kept on disk all the time, not only in the debug mode. A freeze that
// ends with «Закрыть» from recents leaves no chance to copy the journal; the
// next start reads the box instead. Two records:
// - the pulse: a few hundred bytes every 2 s while the app is on screen — when
//   it was last alive, which screen, what was in flight;
// - the tail: the last redacted journal lines, rewritten when new lines appear.
// Both are on the phone only and leave it only through «Скопировать»/«Поделиться».
import AsyncStorage from '@react-native-async-storage/async-storage';

const PULSE_KEY = '@p2pkanban/mobile/v1/diagnostics/pulse';
// The key of the debug-mode tail of build 28: its last tail is still read once.
const TAIL_KEY = '@p2pkanban/mobile/v1/diagnostics/debug-tail';

export type Pulse = {
  /** ISO time of the last write. */
  at: string;
  /** AppState as JS last saw it. `active` here on the next start means JS never saw the app leave. */
  appState: string;
  screen: string | null;
  /** One line: requests in flight, heavy work, heap — the stall watch's snapshot. */
  snapshot: string;
};

export type PreviousRun = { pulse: Pulse | null; tail: string[] };

function parsePulse(raw: string | null): Pulse | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<Pulse>;
    if (typeof value.at !== 'string' || typeof value.appState !== 'string') return null;
    return {
      at: value.at,
      appState: value.appState,
      screen: typeof value.screen === 'string' ? value.screen : null,
      snapshot: typeof value.snapshot === 'string' ? value.snapshot : '',
    };
  } catch {
    return null;
  }
}

function parseTail(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const value = JSON.parse(raw) as unknown;
    return Array.isArray(value) ? value.filter((line): line is string => typeof line === 'string') : [];
  } catch {
    return [];
  }
}

export async function readPreviousRun(): Promise<PreviousRun> {
  const values = new Map(await AsyncStorage.multiGet([PULSE_KEY, TAIL_KEY]));
  return { pulse: parsePulse(values.get(PULSE_KEY) ?? null), tail: parseTail(values.get(TAIL_KEY) ?? null) };
}

/**
 * The verdict on how the previous run ended, or null for an ordinary end.
 * Pure, for tests.
 */
export function previousRunVerdict(pulse: Pulse | null): string | null {
  if (!pulse || pulse.appState !== 'active') return null;
  return 'Прошлый запуск закончился, пока приложение было на экране, и JS-поток не отметил уход в фон '
    + '(зависание, падение или «Закрыть» из недавних во время зависания)'
    + `; последний пульс ${pulse.at}${pulse.screen ? `, экран ${pulse.screen}` : ''}`
    + `${pulse.snapshot ? `; ${pulse.snapshot}` : ''}`;
}

let writing = false;

/** One write at a time; a write that would queue behind another is skipped, the next tick repeats it. */
export function writeBlackBox(pulse: Pulse, tail: string[] | null) {
  if (writing) return false;
  writing = true;
  const pairs: [string, string][] = [[PULSE_KEY, JSON.stringify(pulse)]];
  if (tail) pairs.push([TAIL_KEY, JSON.stringify(tail)]);
  void AsyncStorage.multiSet(pairs)
    .catch(() => undefined)
    .finally(() => { writing = false; });
  return true;
}
