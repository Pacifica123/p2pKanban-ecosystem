export const MAX_EVENT_BYTES = 256 * 1024;
export const MAX_PULL_LIMIT = 1000;

export interface CoordinatorEvent {
  eventId: string;
  replicaId: string;
  replicaSeq: number;
  actorKey: string;
  membershipEpoch: number;
  envelope: unknown;
}

export interface ValidatedCoordinatorEvent extends CoordinatorEvent {
  encodedEnvelope: string;
}

export interface EventValidationResult {
  ok: boolean;
  event?: ValidatedCoordinatorEvent;
  error?: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ACTOR_KEY = /^[A-Za-z0-9:_-]{16,256}$/;

export function validateCoordinatorEvent(input: unknown): EventValidationResult {
  if (!input || typeof input !== 'object') {
    return { ok: false, error: 'event must be an object' };
  }
  const event = input as Partial<CoordinatorEvent>;
  if (typeof event.eventId !== 'string' || !UUID.test(event.eventId)) {
    return { ok: false, error: 'eventId must be a UUID' };
  }
  if (typeof event.replicaId !== 'string' || !UUID.test(event.replicaId)) {
    return { ok: false, error: 'replicaId must be a UUID' };
  }
  if (!Number.isSafeInteger(event.replicaSeq) || Number(event.replicaSeq) < 1) {
    return { ok: false, error: 'replicaSeq must be a positive safe integer' };
  }
  if (typeof event.actorKey !== 'string' || !ACTOR_KEY.test(event.actorKey)) {
    return { ok: false, error: 'actorKey has an unsupported shape' };
  }
  if (!Number.isSafeInteger(event.membershipEpoch) || Number(event.membershipEpoch) < 1) {
    return { ok: false, error: 'membershipEpoch must be a positive safe integer' };
  }

  let encodedEnvelope: string;
  try {
    encodedEnvelope = JSON.stringify(event.envelope);
  } catch {
    return { ok: false, error: 'envelope must be JSON serializable' };
  }
  if (new TextEncoder().encode(encodedEnvelope).byteLength > MAX_EVENT_BYTES) {
    return { ok: false, error: `envelope exceeds ${MAX_EVENT_BYTES} bytes` };
  }

  return {
    ok: true,
    event: {
      eventId: event.eventId,
      replicaId: event.replicaId,
      replicaSeq: Number(event.replicaSeq),
      actorKey: event.actorKey,
      membershipEpoch: Number(event.membershipEpoch),
      envelope: event.envelope,
      encodedEnvelope,
    },
  };
}

export function parsePullWindow(url: URL): { after: number; limit: number } {
  const rawAfter = Number(url.searchParams.get('after') ?? '0');
  const rawLimit = Number(url.searchParams.get('limit') ?? '100');
  const after = Number.isSafeInteger(rawAfter) && rawAfter >= 0 ? rawAfter : 0;
  const limit = Number.isSafeInteger(rawLimit)
    ? Math.min(MAX_PULL_LIMIT, Math.max(1, rawLimit))
    : 100;
  return { after, limit };
}

export function boardRoute(pathname: string): { boardTag: string; suffix: string } | null {
  const match = pathname.match(/^\/v1\/boards\/([A-Za-z0-9_-]{16,128})(\/.*)?$/);
  if (!match) return null;
  return {
    boardTag: match[1],
    suffix: match[2] || '/',
  };
}
