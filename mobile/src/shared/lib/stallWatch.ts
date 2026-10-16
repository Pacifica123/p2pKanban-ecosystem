// Notices when the JS thread stops answering. Taps, the Android back button and
// timers all run on that thread, so a long synchronous pass reads to the person
// as "nothing is clickable". The journal gets one line per stall and names the
// heavy work that was running; work that never finished because the app was
// killed is reported on the next start.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';

import { logLine } from '../errorReport/journal';

const TICK_MS = 1_000;
/** A gap above this is a stall a person notices. */
export const STALL_MS = 1_500;
const MARKER_KEY = '@p2pkanban/mobile/v1/diagnostics/heavy-work';

const running = new Map<number, { label: string; startedAt: number }>();
let nextId = 1;

function labels() {
  return [...running.values()].map((item) => item.label);
}

function persist() {
  const items = [...running.values()].map((item) => ({ label: item.label, startedAt: new Date(item.startedAt).toISOString() }));
  const write = items.length
    ? AsyncStorage.setItem(MARKER_KEY, JSON.stringify(items))
    : AsyncStorage.removeItem(MARKER_KEY);
  void write.catch(() => undefined);
}

/** Runs work that may hold the JS thread; a stall during it is attributed to `label`. */
export async function heavyWork<T>(label: string, run: () => Promise<T>): Promise<T> {
  const id = nextId++;
  running.set(id, { label, startedAt: Date.now() });
  persist();
  try {
    return await run();
  } finally {
    const item = running.get(id);
    running.delete(id);
    persist();
    if (item && Date.now() - item.startedAt >= STALL_MS)
      logLine('info', 'ui', `«${label}» заняло ${((Date.now() - item.startedAt) / 1000).toFixed(1)} с`);
  }
}

/** Pure part of the watchdog, for tests: how long the thread was away beyond one tick. */
export function stallGap(previousTick: number, now: number, tickMs = TICK_MS) {
  return Math.max(0, now - previousTick - tickMs);
}

let installed = false;

export function installStallWatch() {
  if (installed) return;
  installed = true;
  void AsyncStorage.getItem(MARKER_KEY).then((raw) => {
    if (!raw) return;
    void AsyncStorage.removeItem(MARKER_KEY).catch(() => undefined);
    try {
      const items = JSON.parse(raw) as Array<{ label: string; startedAt: string }>;
      if (items.length)
        logLine('warn', 'ui', `Прошлый запуск закрыт, не дождавшись: ${items.map((item) => `«${item.label}» (с ${item.startedAt})`).join(', ')}`);
    } catch { /* an unreadable marker carries nothing */ }
  }).catch(() => undefined);

  let active = AppState.currentState === 'active';
  let last = Date.now();
  // Android pauses JS timers in background: that pause is not a stall.
  AppState.addEventListener('change', (state) => {
    active = state === 'active';
    last = Date.now();
  });
  setInterval(() => {
    const now = Date.now();
    const gap = stallGap(last, now);
    last = now;
    if (!active || gap < STALL_MS) return;
    const during = labels();
    logLine('warn', 'ui', `JS-поток не отвечал ${(gap / 1000).toFixed(1)} с${during.length ? `; шло: ${during.join(', ')}` : ''}`);
  }, TICK_MS);
}
