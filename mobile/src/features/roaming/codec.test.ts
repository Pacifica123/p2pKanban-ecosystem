import { decodeBoardKey, deriveBoardTag, openRoamingEvent, sealRoamingEvent } from './codec';
import { ROAMING_PROTOCOL_VERSION, type RoamingBoardEvent } from './types';

const boardKeyText = 'BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc';
const boardKey = decodeBoardKey(boardKeyText);
const workspaceId = '018f22e2-355a-7ba2-8ef0-d7bc788ceec8';
const boardId = '018f22e2-355a-7ba2-8ef0-d7bc788ceec9';
const boardTag = deriveBoardTag(boardKey, boardId);

function event(): RoamingBoardEvent {
  return {
    protocolVersion: ROAMING_PROTOCOL_VERSION,
    eventId: '018f22e2-1d58-7f08-9a36-1f96bd9854b1',
    workspaceId,
    boardId,
    capabilityEpoch: 1,
    replicaId: '018f22e2-29cc-7ad6-aa57-b61d74a14e52',
    replicaSeq: 1,
    logicalClock: 7,
    entityType: 'card',
    entityId: '018f22e2-355a-7ba2-8ef0-d7bc788ceeca',
    operation: 'card.put',
    fieldMask: ['title'],
    payload: { card: { title: 'не утечь в relay' } },
    occurredAt: '2026-07-28T12:00:00.000Z',
  };
}

test('encrypted roaming record round-trips and hides board data', () => {
  const sealed = sealRoamingEvent(event(), boardKey, boardTag, new Uint8Array(24).fill(9));
  expect(sealed).not.toContain(workspaceId);
  expect(sealed).not.toContain('не утечь');
  expect(openRoamingEvent(sealed, boardKey, boardTag)).toEqual(event());
});

test('wrong board key cannot decrypt an event', () => {
  const sealed = sealRoamingEvent(event(), boardKey, boardTag, new Uint8Array(24).fill(2));
  const wrong = new Uint8Array(32).fill(8);
  expect(() => openRoamingEvent(sealed, wrong, boardTag)).toThrow();
});
