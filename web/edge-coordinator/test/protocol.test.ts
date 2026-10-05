import { describe, expect, it } from 'vitest';

import { boardRoute, parsePullWindow, validateCoordinatorEvent } from '../src/protocol';

describe('coordinator event contract', () => {
  it('accepts a bounded event with stable replica sequence', () => {
    const result = validateCoordinatorEvent({
      eventId: '018f22e2-1d58-7f08-9a36-1f96bd9854b1',
      replicaId: '018f22e2-29cc-7ad6-aa57-b61d74a14e52',
      replicaSeq: 4,
      actorKey: 'device:6f3ac9f40e6f4cb1',
      membershipEpoch: 2,
      envelope: { protocolVersion: 'p2p-kanban-sync/1' },
    });
    expect(result.ok).toBe(true);
    expect(result.event?.encodedEnvelope).toContain('p2p-kanban-sync/1');
  });

  it('rejects an invalid sequence before storage', () => {
    const result = validateCoordinatorEvent({
      eventId: '018f22e2-1d58-7f08-9a36-1f96bd9854b1',
      replicaId: '018f22e2-29cc-7ad6-aa57-b61d74a14e52',
      replicaSeq: 0,
      actorKey: 'device:6f3ac9f40e6f4cb1',
      membershipEpoch: 2,
      envelope: {},
    });
    expect(result).toEqual({ ok: false, error: 'replicaSeq must be a positive safe integer' });
  });
});

describe('routing and cursor bounds', () => {
  it('keeps the board tag opaque and extracts only the suffix', () => {
    expect(boardRoute('/v1/boards/MjMyYjgzM2YtZmFrZS10YWc/events')).toEqual({
      boardTag: 'MjMyYjgzM2YtZmFrZS10YWc',
      suffix: '/events',
    });
  });

  it('clamps abusive pull limits', () => {
    expect(parsePullWindow(new URL('https://example.test/events?after=5&limit=999999'))).toEqual({
      after: 5,
      limit: 1000,
    });
  });
});
