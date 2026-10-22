import type { Event as NostrEvent, Filter } from 'nostr-tools';
import { finalizeEvent, verifyEvent } from 'nostr-tools/pure';

import { trace } from '../../shared/errorReport/journal';
import { mapInSlices, throwIfCanceled } from '../../shared/lib/uiBudget';

/**
 * Three deadlines instead of one 8 s budget (2026-10-22, er-01235c9feb389f7a):
 * in mobile data the TLS handshake alone ate most of the 8 s, and a relay that
 * was still streaming a full board history counted as silent.
 */
/** Opening the socket: DNS, TCP and TLS. */
export const RELAY_OPEN_TIMEOUT_MS = 10_000;
/** After the socket opened: longest silence between two frames. */
export const RELAY_QUIET_TIMEOUT_MS = 8_000;
/** Whole exchange with one relay, opening included. */
export const RELAY_TOTAL_TIMEOUT_MS = 30_000;

function withRelay<T>(
  url: string,
  run: (socket: WebSocket, finish: (value: T) => void, fail: (reason: unknown) => void) => void,
) {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    let opened = false;
    let frames = 0;
    const socket = new WebSocket(url);
    const stop = () => {
      settled = true;
      clearTimeout(quiet);
      clearTimeout(total);
      socket.close();
    };
    const finish = (value: T) => {
      if (settled) return;
      stop();
      resolve(value);
    };
    const fail = (reason: unknown) => {
      if (settled) return;
      stop();
      reject(reason instanceof Error ? reason : new Error(`Релей ${url} недоступен.`));
    };
    // An unopened socket points at the network (blocked or filtered), an opened one at the relay.
    let quiet = setTimeout(() => fail(new Error(
      `Релей ${url} не открыл соединение за ${RELAY_OPEN_TIMEOUT_MS / 1000} с: сеть не пускает к нему.`)), RELAY_OPEN_TIMEOUT_MS);
    const total = setTimeout(() => fail(new Error(opened
      ? `Релей ${url} отвечал, но не закончил за ${RELAY_TOTAL_TIMEOUT_MS / 1000} с (сообщений: ${frames}).`
      : `Релей ${url} не открыл соединение за ${RELAY_TOTAL_TIMEOUT_MS / 1000} с: сеть не пускает к нему.`)), RELAY_TOTAL_TIMEOUT_MS);
    const waitQuietly = () => {
      clearTimeout(quiet);
      quiet = setTimeout(() => fail(new Error(frames
        ? `Релей ${url} замолчал на ${RELAY_QUIET_TIMEOUT_MS / 1000} с, не закончив ответ (сообщений: ${frames}).`
        : `Релей ${url} открыл соединение, но не ответил за ${RELAY_QUIET_TIMEOUT_MS / 1000} с.`)), RELAY_QUIET_TIMEOUT_MS);
    };
    socket.onerror = () => fail(new Error(`Не удалось открыть ${url}.`));
    socket.onclose = () => fail(new Error(`Релей ${url} закрыл соединение до ответа.`));
    socket.onopen = () => {
      if (settled) return;
      opened = true;
      waitQuietly();
      try {
        run(socket, finish, fail);
      } catch (error) {
        fail(error);
        return;
      }
      // Every frame from the relay, whatever it is, proves the relay is still answering.
      const handle = socket.onmessage;
      socket.onmessage = (message) => {
        if (settled) return;
        frames += 1;
        waitQuietly();
        handle?.call(socket, message);
      };
    };
  });
}

async function publishOne(url: string, event: NostrEvent) {
  return withRelay<string>(url, (socket, finish, fail) => {
    socket.onmessage = (message) => {
      try {
        const frame = JSON.parse(String(message.data)) as unknown[];
        if (frame[0] !== 'OK' || frame[1] !== event.id) return;
        if (frame[2] === true) finish(url);
        else fail(new Error(String(frame[3] || `Релей ${url} отклонил событие.`)));
      } catch (error) {
        fail(error);
      }
    };
    socket.send(JSON.stringify(['EVENT', event]));
  });
}

function matchesFilter(event: NostrEvent, filter: Filter) {
  return Boolean(event && typeof event === 'object' && typeof event.id === 'string'
    && Array.isArray(event.tags)
    && (!filter.kinds || filter.kinds.includes(event.kind))
    && (!filter['#d'] || event.tags.some(tag => tag[0] === 'd' && tag[1] !== undefined && filter['#d']!.includes(tag[1])))
    && (!filter['#p'] || event.tags.some(tag => tag[0] === 'p' && tag[1] !== undefined && filter['#p']!.includes(tag[1])))
    && (!filter['#s'] || event.tags.some(tag => tag[0] === 's' && tag[1] !== undefined && filter['#s']!.includes(tag[1]))));
}

/**
 * Collects frames only. Signatures are checked later, once per distinct event
 * and in time slices: verifying inside onmessage blocked the UI thread for the
 * whole board history on every poll.
 */
export async function fetchOne(url: string, filter: Filter) {
  return withRelay<NostrEvent[]>(url, (socket, finish, fail) => {
    const subscriptionId = `p2pk-${Math.random().toString(36).slice(2)}`;
    const events: NostrEvent[] = [];
    socket.onmessage = (message) => {
      try {
        const frame = JSON.parse(String(message.data)) as unknown[];
        if (frame[0] === 'EVENT' && frame[1] === subscriptionId) {
          const event = frame[2] as NostrEvent;
          if (matchesFilter(event, filter)) events.push(event);
        }
        if (frame[0] === 'EOSE' && frame[1] === subscriptionId) {
          socket.send(JSON.stringify(['CLOSE', subscriptionId]));
          finish(events);
        }
      } catch (error) {
        fail(error);
      }
    };
    socket.send(JSON.stringify(['REQ', subscriptionId, filter]));
  });
}

export interface RelayFetchOptions {
  /** Nostr ids already verified and stored: their content is fixed by the id. */
  knownIds?: ReadonlySet<string>;
  /** Unix seconds; omitted for a full pull. */
  since?: number;
  signal?: AbortSignal | null;
}

/** Deduplicates across relays, skips known ids, verifies the rest without freezing the UI. */
async function verifyCollected(
  settled: PromiseSettledResult<NostrEvent[]>[],
  options: RelayFetchOptions,
) {
  throwIfCanceled(options.signal);
  const candidates = new Map<string, NostrEvent[]>();
  let skipped = 0;
  for (const result of settled) {
    if (result.status !== 'fulfilled') continue;
    for (const event of result.value) {
      if (options.knownIds?.has(event.id)) { skipped += 1; continue; }
      const group = candidates.get(event.id);
      if (!group) candidates.set(event.id, [event]);
      else if (!group.some(item => item.sig === event.sig && item.content === event.content)) group.push(event);
    }
  }
  // A forged copy under a real id must not hide the genuine copy from another relay.
  const verified = await mapInSlices([...candidates.values()],
    group => group.find(event => verifyEvent(event)) || null, { signal: options.signal });
  return { events: verified.filter((event): event is NonNullable<typeof event> => Boolean(event)) as NostrEvent[], skipped };
}

export function createSignedNostrEvent(input: {
  secretKey: Uint8Array;
  kind: number;
  boardTag: string;
  content: string;
  createdAt?: number;
}) {
  return finalizeEvent({
    kind: input.kind,
    created_at: input.createdAt ?? Math.floor(Date.now() / 1000),
    tags: [
      ['d', input.boardTag],
      ['t', 'p2pkanban-roaming'],
      ['v', '1'],
    ],
    content: input.content,
  }, input.secretKey);
}

export async function publishToRelays(
  relays: string[],
  event: NostrEvent,
  minimumAcks: number,
) {
  // Count distinct relay endpoints, never duplicate URLs or an empty quorum.
  relays = [...new Set(relays)];
  if (!relays.length || !Number.isInteger(minimumAcks) || minimumAcks < 1 || minimumAcks > relays.length) {
    throw new Error('Некорректный набор relay или число обязательных подтверждений.');
  }
  const settled = await Promise.allSettled(relays.map((relay) => publishOne(relay, event)));
  const acceptedRelays = settled.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []);
  const failedRelays = relays.filter((relay) => !acceptedRelays.includes(relay));
  trace('relay', () => `отправка ${event.id.slice(0, 12)}: приняли ${acceptedRelays.length} из ${relays.length}, нужно ${minimumAcks}`
    + settled.flatMap((result, index) => result.status === 'rejected'
      ? [`; ${relays[index]}: ${result.reason instanceof Error ? result.reason.message : 'ошибка WebSocket'}`] : []).join(''));
  if (acceptedRelays.length < minimumAcks) {
    throw new Error(
      `Relay-журнал принят: ${acceptedRelays.length} из ${minimumAcks} обязательных подтверждений.`,
    );
  }
  return { acceptedRelays, failedRelays };
}

export async function fetchFromRelays(input: {
  relays: string[];
  kind: number;
  boardTag: string;
} & RelayFetchOptions) {
  const filter: Filter = {
    kinds: [input.kind],
    '#d': [input.boardTag],
    ...(input.since ? { since: input.since } : {}),
  };
  const settled = await Promise.allSettled(input.relays.map((relay) => fetchOne(relay, filter)));
  const relayCount = settled.filter(result => result.status === 'fulfilled').length;
  trace('relay', () => `чтение доски ${input.boardTag.slice(0, 8)}${input.since ? ` с ${new Date(input.since * 1000).toISOString()}` : ' целиком'}:`
    + ` ответили ${relayCount} из ${input.relays.length}`
    + settled.flatMap((result, index) => result.status === 'rejected'
      ? [`; ${input.relays[index]}: ${result.reason instanceof Error ? result.reason.message : 'ошибка WebSocket'}`] : []).join(''));
  if (!relayCount) {
    const errors = settled.flatMap((r, i) => r.status === 'rejected' ? [`${input.relays[i]}: ${r.reason instanceof Error ? r.reason.message : 'ошибка WebSocket'}`] : []);
    throw new Error(`Релейная связь недоступна. ${errors.join('; ')}`);
  }
  const { events, skipped } = await verifyCollected(settled, input);
  return { events, relayCount, skipped };
}

export async function fetchDeviceCatalogEvents(input: {
  relays: string[]; kind: number; recipient: string;
} & RelayFetchOptions) {
  const filter: Filter = { kinds: [input.kind], '#p': [input.recipient] };
  const settled = await Promise.allSettled(input.relays.map(relay => fetchOne(relay, filter)));
  const relayCount = settled.filter(result => result.status === 'fulfilled').length;
  if (!relayCount) {
    const errors = settled.flatMap((r, i) => r.status === 'rejected' ? [`${input.relays[i]}: ${r.reason instanceof Error ? r.reason.message : 'ошибка WebSocket'}`] : []);
    throw new Error(`Каталог досок недоступен: ни один релей не ответил. ${errors.join('; ')}`);
  }
  const { events } = await verifyCollected(settled, input);
  return {events, relayCount};
}

/** Ring records (account-ring/1) and meeting mail (rendezvous/1): any filter, deduplicated and verified. */
export async function fetchTagged(relays: string[], filter: Filter, options: RelayFetchOptions = {}) {
  const settled = await Promise.allSettled(relays.map(relay => fetchOne(relay, filter)));
  const relayCount = settled.filter(result => result.status === 'fulfilled').length;
  const errors = settled.flatMap((r, i) => r.status === 'rejected' ? [`${relays[i]}: ${r.reason instanceof Error ? r.reason.message : 'ошибка WebSocket'}`] : []);
  trace('relay', () => `кольцо: kind ${(filter.kinds || []).join(',')}: ответили ${relayCount} из ${relays.length}${errors.length ? `; ${errors.join('; ')}` : ''}`);
  if (!relayCount) throw new Error(`Ни один relay не ответил. ${errors.join('; ')}`);
  const { events } = await verifyCollected(settled, options);
  return { events, relayCount, errors };
}

/** Publish to every relay; the caller decides what quorum means. */
export async function publishEach(relays: string[], event: NostrEvent) {
  relays = [...new Set(relays)];
  const settled = await Promise.allSettled(relays.map(relay => publishOne(relay, event)));
  const accepted = settled.flatMap(result => result.status === 'fulfilled' ? [result.value] : []);
  const errors = settled.flatMap((r, i) => r.status === 'rejected' ? [`${relays[i]}: ${r.reason instanceof Error ? r.reason.message : 'ошибка WebSocket'}`] : []);
  trace('relay', () => `кольцо: отправка kind ${event.kind} ${event.id.slice(0, 12)}: приняли ${accepted.length} из ${relays.length}`);
  return { accepted, failed: relays.filter(relay => !accepted.includes(relay)), errors };
}
