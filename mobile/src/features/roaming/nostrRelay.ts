import type { Event as NostrEvent, Filter } from 'nostr-tools';
import { finalizeEvent, verifyEvent } from 'nostr-tools/pure';

import { mapInSlices, throwIfCanceled } from '../../shared/lib/uiBudget';

const RELAY_TIMEOUT_MS = 8_000;

function withRelay<T>(
  url: string,
  run: (socket: WebSocket, finish: (value: T) => void, fail: (reason: unknown) => void) => void,
) {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const socket = new WebSocket(url);
    const finish = (value: T) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.close();
      resolve(value);
    };
    const fail = (reason: unknown) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.close();
      reject(reason instanceof Error ? reason : new Error(`Релей ${url} недоступен.`));
    };
    const timer = setTimeout(() => fail(new Error(`Релей ${url} не ответил вовремя.`)), RELAY_TIMEOUT_MS);
    socket.onerror = () => fail(new Error(`Не удалось открыть ${url}.`));
    socket.onclose = () => fail(new Error(`Релей ${url} закрыл соединение до ответа.`));
    socket.onopen = () => {
      try {
        run(socket, finish, fail);
      } catch (error) {
        fail(error);
      }
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
    && (!filter['#p'] || event.tags.some(tag => tag[0] === 'p' && tag[1] !== undefined && filter['#p']!.includes(tag[1]))));
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
  if (!relayCount) throw new Error('Каталог реплик недоступен через настроенные relay.');
  const { events } = await verifyCollected(settled, input);
  return {events, relayCount};
}
