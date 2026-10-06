/**
 * The JS thread also delivers taps and the Android back button. Heavy loops
 * (signature checks, decryption, journal replay) must give it back regularly,
 * otherwise "leave the board" waits for the loop to finish.
 */
export const UI_SLICE_MS = 8;

export class SyncCanceledError extends Error {
  constructor() {
    super('Синхронизация остановлена: экран закрыт.');
    this.name = 'SyncCanceledError';
  }
}

export function isSyncCanceled(error: unknown) {
  return error instanceof SyncCanceledError;
}

export function throwIfCanceled(signal?: AbortSignal | null) {
  if (signal?.aborted) throw new SyncCanceledError();
}

/** One macrotask: queued touch and back events run before we continue. */
export function yieldToUi() {
  return new Promise<void>((resolve) => setTimeout(resolve, 0));
}

/**
 * Maps items in time slices. Between slices the UI gets the thread back and a
 * closed screen stops the work instead of finishing it.
 */
export async function mapInSlices<T, R>(
  items: readonly T[],
  map: (item: T) => R,
  options: { signal?: AbortSignal | null; sliceMs?: number; now?: () => number } = {},
): Promise<R[]> {
  const sliceMs = options.sliceMs ?? UI_SLICE_MS;
  const now = options.now ?? Date.now;
  const result: R[] = [];
  let sliceStart = now();
  for (const item of items) {
    throwIfCanceled(options.signal);
    result.push(map(item));
    if (now() - sliceStart >= sliceMs) {
      await yieldToUi();
      sliceStart = now();
    }
  }
  throwIfCanceled(options.signal);
  return result;
}
