// Notices when the JS thread stops answering (docs/architecture/stall-watch-20261020.md).
// Taps, the Android back button and timers all run on that thread, so a long
// synchronous pass reads to the person as "nothing is clickable". On Android
// the timers are also paced by the UI thread (Choreographer), so a late tick
// means one of the two was held.
//
// What the watch keeps:
// - a stall line (≥ 1.5 s) with a snapshot: the heavy work that was running,
//   requests to the node in flight and their age, the screen, the garbage
//   collector's share of the pause and how many journal lines JS still wrote
//   during it (lines inside the pause mean JS ran while the timers did not);
// - hitches (≥ 0.7 s): the precursors, one line at most every 30 s;
// - in the debug mode a minute summary: worst delay, hitches, heap;
// - the black box on disk (../debug/blackBox.ts) every 2 s while on screen,
//   and right after a stall, so a freeze that ends with a kill is readable on
//   the next start.
// Work that never finished because the app was killed is reported on the next start.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';

import { inFlightRequests } from '../api/client';
import { previousRunVerdict, readPreviousRun, writeBlackBox } from '../debug/blackBox';
import { isJournalDebugMode, journalCleanLines, journalEntries, lastJournalSeq, logLine, trace } from '../errorReport/journal';

const TICK_MS = 500;
/** A gap above this is a stall a person notices. */
export const STALL_MS = 1_500;
/** A gap above this is a hitch: not yet a freeze, but worth a line. */
export const HITCH_MS = 700;
/** Gaps above this count in the debug-mode summary. */
const JANK_MS = 200;
const HITCH_LINE_EVERY_MS = 30_000;
/** Timers that were due during a pause run just before the watch does; their lines are not "inside". */
const LATE_TIMERS_MS = 250;
const PULSE_EVERY_MS = 2_000;
/** The tail is larger: rewritten at most this often, except right after a pause or a state change. */
const TAIL_EVERY_MS = 4_000;
const SUMMARY_EVERY_MS = 60_000;
/** Journal lines kept in the black box: ordinary and debug mode. */
export const BOX_LINES = 200;
export const BOX_DEBUG_LINES = 500;
const MARKER_KEY = '@p2pkanban/mobile/v1/diagnostics/heavy-work';

const running = new Map<number, { label: string; startedAt: number }>();
let nextId = 1;
let screen: string | null = null;
let previousTail: string[] = [];

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

/** The navigator reports the visible screen; the snapshot names it. */
export function noteScreen(name: string | null) {
  screen = name;
}

/** The redacted journal tail the previous run left in the black box, old first. */
export function previousRunLines() {
  return previousTail;
}

/** Pure part of the watchdog, for tests: how long the thread was away beyond one tick. */
export function stallGap(previousTick: number, now: number, tickMs = TICK_MS) {
  return Math.max(0, now - previousTick - tickMs);
}

export type HeapStats = { heapBytes: number; gcCount: number; gcMs: number };

function num(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** Hermes counters; zeros where the engine has none. */
export function heapStats(): HeapStats {
  const hermes = (globalThis as { HermesInternal?: { getInstrumentedStats?: () => Record<string, unknown> } }).HermesInternal;
  let stats: Record<string, unknown> = {};
  try { stats = hermes?.getInstrumentedStats?.() ?? {}; } catch { /* no counters */ }
  return {
    heapBytes: num(stats.js_heapSize),
    gcCount: num(stats.js_numGCs),
    // Hermes reports seconds.
    gcMs: num(stats.js_gcTime) * 1000,
  };
}

export type Snapshot = {
  heavy: string[];
  requests: Array<{ method: string; path: string; ageMs: number }>;
  screen: string | null;
  heap: HeapStats;
};

function shortPath(path: string) {
  // Ids are long and say nothing here; the route does.
  return path.replace(/^\/api\/v1/, '').replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, (id) => id.slice(0, 8));
}

/** One line for the journal and the pulse. Pure, for tests. */
export function describeSnapshot(snapshot: Snapshot) {
  const parts: string[] = [];
  if (snapshot.heavy.length) parts.push(`шло: ${snapshot.heavy.join(', ')}`);
  const { requests } = snapshot;
  if (requests.length) {
    const oldest = [...requests].sort((left, right) => right.ageMs - left.ageMs).slice(0, 4)
      .map((request) => `${request.method} ${shortPath(request.path)} ${(request.ageMs / 1000).toFixed(1)} с`);
    parts.push(`запросов к узлу в полёте ${requests.length}: ${oldest.join(', ')}${requests.length > oldest.length ? ', …' : ''}`);
  } else {
    parts.push('запросов к узлу в полёте нет');
  }
  if (snapshot.screen) parts.push(`экран ${snapshot.screen}`);
  if (snapshot.heap.heapBytes) parts.push(`куча ${(snapshot.heap.heapBytes / 1024 / 1024).toFixed(0)} МБ`);
  return parts.join('; ');
}

function snapshot(): Snapshot {
  return { heavy: labels(), requests: inFlightRequests(), screen, heap: heapStats() };
}

/** What happened inside a pause. Pure, for tests. */
export function describePause(input: { from: number; to: number; linesInside: number; before: HeapStats; after: HeapStats }) {
  const parts: string[] = [];
  const gcCount = input.after.gcCount - input.before.gcCount;
  const gcMs = input.after.gcMs - input.before.gcMs;
  if (input.after.gcCount || input.after.gcMs) {
    parts.push(gcCount > 0 ? `сборка мусора за паузу: ${gcCount} раз, ${(gcMs / 1000).toFixed(1)} с` : 'сборки мусора за паузу не было');
  }
  parts.push(input.linesInside
    ? `JS писал журнал во время паузы (${input.linesInside} строк): стояли таймеры, вероятно UI-поток`
    : 'JS за паузу ничего не записал');
  return parts.join('; ');
}

function linesBetween(from: number, to: number) {
  let count = 0;
  for (const entry of journalEntries()) if (entry.at > from && entry.at < to) count += 1;
  return count;
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

  let appState: string = AppState.currentState ?? 'active';
  let last = Date.now();
  let lastHeap = heapStats();
  // What the last on-time tick saw: a stall line describes the moment the pause began.
  let lastSeen = snapshot();
  let lastHitchLine = 0;
  let lastPulse = 0;
  let lastTail = 0;
  let boxSeq = -1;
  // The previous run is read before the first pulse overwrites it.
  let boxReady = false;
  let summary = { since: Date.now(), worst: 0, janks: 0 };

  void readPreviousRun().then(({ pulse, tail }) => {
    previousTail = tail;
    const verdict = previousRunVerdict(pulse);
    if (verdict) logLine('warn', 'ui', verdict);
  }).catch(() => undefined).finally(() => { boxReady = true; });

  function pulse(now: number, urgent = false) {
    if (!boxReady) return;
    const seq = lastJournalSeq();
    const tailChanged = seq !== boxSeq && (urgent || now - lastTail >= TAIL_EVERY_MS);
    const written = writeBlackBox(
      { at: new Date(now).toISOString(), appState, screen, snapshot: describeSnapshot(snapshot()) },
      tailChanged ? journalCleanLines(isJournalDebugMode() ? BOX_DEBUG_LINES : BOX_LINES) : null,
    );
    if (!written) return;
    lastPulse = now;
    if (tailChanged) { boxSeq = seq; lastTail = now; }
  }

  // Android pauses JS timers in background: that pause is not a stall.
  AppState.addEventListener('change', (state) => {
    appState = state;
    last = Date.now();
    lastHeap = heapStats();
    lastSeen = snapshot();
    pulse(last, true);
  });

  setInterval(() => {
    const now = Date.now();
    const gap = stallGap(last, now);
    const from = last;
    last = now;
    const heap = heapStats();
    const before = lastHeap;
    lastHeap = heap;
    const seenBefore = lastSeen;
    lastSeen = { heavy: labels(), requests: inFlightRequests(now), screen, heap };
    if (appState !== 'active') return;

    if (gap >= JANK_MS) summary.janks += 1;
    summary.worst = Math.max(summary.worst, gap);
    if (gap >= STALL_MS) {
      logLine('warn', 'ui', `JS-поток не отвечал ${(gap / 1000).toFixed(1)} с; перед паузой ${describeSnapshot(seenBefore)}; `
        + `после неё запросов в полёте ${lastSeen.requests.length}; `
        + describePause({ from, to: now, linesInside: linesBetween(from + TICK_MS, now - LATE_TIMERS_MS), before, after: heap }));
      pulse(now, true);
      return;
    }
    if (gap >= HITCH_MS && now - lastHitchLine >= HITCH_LINE_EVERY_MS) {
      lastHitchLine = now;
      logLine('warn', 'ui', `предвестник: JS-поток запоздал на ${(gap / 1000).toFixed(1)} с; перед этим ${describeSnapshot(seenBefore)}`);
    }
    if (now - summary.since >= SUMMARY_EVERY_MS) {
      const { worst, janks } = summary;
      summary = { since: now, worst: 0, janks: 0 };
      trace('ui', () => `минута: худшая задержка ${worst} мс, задержек больше ${JANK_MS} мс: ${janks}; ${describeSnapshot(snapshot())}`);
    }
    if (now - lastPulse >= PULSE_EVERY_MS) pulse(now);
  }, TICK_MS);
}
