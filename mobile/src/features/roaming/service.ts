import {operationActivity} from './activity';
import {verifyReplicationChain} from '../deviceLink/protocol';
import * as Crypto from 'expo-crypto';
import { getPublicKey, generateSecretKey } from 'nostr-tools/pure';

import type { Card } from '../../shared/types/api';
import {
  isChecklistOperation,
  operationCardId,
  type LocalBoardSnapshot,
  type LocalOperation,
} from '../localFirst/model';
import {
  decodeBoardKey,
  deriveBoardTag,
  openRoamingEvent,
  sealRoamingEvent,
} from './codec';
import { loadJournal, mergeJournal, projectJournal, saveJournal, serializeReplica } from './journal';
import {
  createSignedNostrEvent,
  fetchFromRelays,
  publishToRelays,
} from './nostrRelay';
import {
  getOrCreateRoamingDeviceSecret,
  loadRoamingCapability,
  saveRoamingCapability,
} from './storage';
import {
  ROAMING_CAPABILITY_VERSION,
  ROAMING_PROTOCOL_VERSION,
  type RoamingBoardEvent,
  type RoamingCapability,
  type RoamingPublishResult,
  type RoamingPullResult,
} from './types';

function validateCapability(capability: RoamingCapability) {
  if (
    capability.formatVersion !== ROAMING_CAPABILITY_VERSION
    || capability.protocolVersion !== ROAMING_PROTOCOL_VERSION
  ) {
    throw new Error('Узел вернул несовместимый формат независимой доски.');
  }
  const key = decodeBoardKey(capability.boardKey);
  if (deriveBoardTag(key, capability.boardId) !== capability.boardTag) {
    throw new Error('Ключ доски не соответствует её анонимному тегу.');
  }
  if (capability.relays.length < 2) {
    throw new Error('Для независимой доски нужны хотя бы два реле.');
  }
  if (!Number.isInteger(capability.capabilityEpoch) || capability.capabilityEpoch < 1) {
    throw new Error('Узел вернул некорректное поколение доступа к доске.');
  }
  if (!Number.isInteger(capability.minimumRelayAcks) || capability.minimumRelayAcks < 1
    || capability.minimumRelayAcks > capability.relays.length) throw new Error('Некорректное число подтверждений relay.');
  return key;
}

async function identity() {
  const secretKey = await getOrCreateRoamingDeviceSecret(() => generateSecretKey());
  const publicKey = getPublicKey(secretKey);
  const replicaId = [
    publicKey.slice(0, 8),
    publicKey.slice(8, 12),
    `4${publicKey.slice(13, 16)}`,
    `a${publicKey.slice(17, 20)}`,
    publicKey.slice(20, 32),
  ].join('-');
  return { secretKey, publicKey, replicaId };
}

export async function getRoamingAuthorPublicKey() {
  return (await identity()).publicKey;
}

function fieldsFor(operation: LocalOperation) {
  if (operation.kind === 'board.appearance.update') return ['appearance'];
  if (operation.kind === 'card.delete') return ['__lifecycle'];
  if (isChecklistOperation(operation)) return ['checklists'];
  if (operation.kind === 'card.create') return ['*'];
  if (operation.kind === 'card.update') return Object.keys(operation.payload.input);
  if (operation.kind === 'card.move') return ['columnId', 'position', 'updatedAt'];
  return ['isArchived', 'archivedAt', 'updatedAt'];
}

function checklistDeltaFor(
  operation: LocalOperation,
  checklists: NonNullable<LocalBoardSnapshot['checklistsByCardId'][string]>,
) {
  if (!isChecklistOperation(operation)) return null;
  const cardId = operationCardId(operation);
  if (operation.kind === 'checklist.delete') {
    return {
      kind: 'checklist.delete',
      cardId,
      checklistId: operation.entityId,
      fieldMask: ['__lifecycle'],
      deletedAt: operation.createdAt,
    };
  }
  if (operation.kind === 'checklist.item.delete') {
    return {
      kind: 'checklist_item.delete',
      cardId,
      checklistId: operation.payload.checklistId,
      itemId: operation.entityId,
      fieldMask: ['__lifecycle'],
      deletedAt: operation.createdAt,
    };
  }

  const checklistId = operation.kind === 'checklist.item.create'
    || operation.kind === 'checklist.item.update'
    ? operation.payload.checklistId
    : operation.entityId;
  const checklist = checklists.find((candidate) => candidate.id === checklistId);
  if (!checklist) throw new Error('Чек-лист для relay-события не найден.');

  if (operation.kind === 'checklist.create' || operation.kind === 'checklist.update') {
    return {
      kind: 'checklist.put',
      cardId,
      checklistId,
      fieldMask: operation.kind === 'checklist.create'
        ? ['*']
        : Object.keys(operation.payload.input),
      checklist: { ...checklist, items: [] },
    };
  }

  const item = checklist.items.find((candidate) => candidate.id === operation.entityId);
  if (!item) throw new Error('Пункт чек-листа для relay-события не найден.');
  return {
    kind: 'checklist_item.put',
    cardId,
    checklistId,
    itemId: item.id,
    fieldMask: operation.kind === 'checklist.item.create'
      ? ['*']
      : Object.keys(operation.payload.input),
    item,
  };
}

function eventForCard(input: {
  capability: RoamingCapability;
  operation: LocalOperation;
  card: Card;
  checklists: LocalBoardSnapshot['checklistsByCardId'][string];
  replicaId: string;
  replicaSeq: number;
  logicalClock: number;
}): RoamingBoardEvent {
  if (input.operation.kind === 'card.delete') {
    return {
      protocolVersion: ROAMING_PROTOCOL_VERSION,
      eventId: input.operation.id,
      workspaceId: input.capability.workspaceId,
      boardId: input.capability.boardId,
      capabilityEpoch: input.capability.capabilityEpoch,
      replicaId: input.replicaId,
      replicaSeq: input.replicaSeq,
      logicalClock: input.logicalClock,
      entityType: 'card',
      entityId: input.operation.entityId,
      operation: 'card.delete',
      fieldMask: fieldsFor(input.operation),
      payload: { deletedAt: input.operation.createdAt },
      occurredAt: input.operation.createdAt,
    };
  }
  const checklistDelta = checklistDeltaFor(input.operation, input.checklists || []);
  return {
    protocolVersion: ROAMING_PROTOCOL_VERSION,
    eventId: input.operation.id,
    workspaceId: input.capability.workspaceId,
    boardId: input.capability.boardId,
    capabilityEpoch: input.capability.capabilityEpoch,
    replicaId: input.replicaId,
    replicaSeq: input.replicaSeq,
    logicalClock: input.logicalClock,
    entityType: 'card',
    entityId: input.card.id,
    operation: 'card.put',
    fieldMask: fieldsFor(input.operation),
    payload: {
      card: input.card,
      ...(checklistDelta ? { checklistDelta } : {}),
    },
    occurredAt: input.operation.createdAt,
  };
}

export async function publishEvent(
  capability: RoamingCapability,
  event: RoamingBoardEvent,
): Promise<RoamingPublishResult> {
  const boardKey = validateCapability(capability);
  const { secretKey } = await identity();
  if(capability.delegationChain?.length)event={...event,payload:{...event.payload,_deviceDelegation:capability.delegationChain}};
  const nostr = await serializeReplica(async () => {
    const journal = await loadJournal(capability, null);
    if (journal.wire?.[event.eventId]) return journal.wire[event.eventId]!;
    const wire = createSignedNostrEvent({secretKey, kind: capability.eventKind,
      boardTag: capability.boardTag,
      content: sealRoamingEvent(event, boardKey, capability.boardTag, Crypto.getRandomBytes(24))});
    if (journal.events.some(item => item.eventId === event.eventId)) {
      journal.wire = {...journal.wire, [event.eventId]: wire};
      await saveJournal(capability.boardId, journal);
    }
    return wire;
  });
  const result = await publishToRelays(
    capability.relays,
    nostr,
    capability.minimumRelayAcks,
  );
  return { eventId: event.eventId, ...result };
}

export async function installRoamingCapability(capability: RoamingCapability) {
  validateCapability(capability);
  await saveRoamingCapability(capability);
  return capability;
}

export async function publishBoardSnapshot(
  capability: RoamingCapability,
  snapshot: LocalBoardSnapshot,
) {
  if (!capability.canWrite) {
    throw new Error('Гостевой доступ не разрешает публиковать снимок доски.');
  }
  const { replicaId } = await identity();
  const timestamp = Date.now();
  const event: RoamingBoardEvent = {
    protocolVersion: ROAMING_PROTOCOL_VERSION,
    eventId: Crypto.randomUUID(),
    workspaceId: capability.workspaceId,
    boardId: capability.boardId,
    capabilityEpoch: capability.capabilityEpoch,
    replicaId,
    replicaSeq: timestamp,
    logicalClock: timestamp,
    entityType: 'board',
    entityId: capability.boardId,
    operation: 'board.snapshot',
    fieldMask: ['*'],
    payload: { snapshot },
    occurredAt: new Date(timestamp).toISOString(),
  };
  await serializeReplica(async () => {
    let journal = await loadJournal(capability, snapshot);
    event.payload.fieldVersions = projectJournal(journal).state.fieldVersions;
    journal = mergeJournal(journal, [event]);
    journal.pending.push(event.eventId);
    await saveJournal(capability.boardId, journal);
  });
  const result = await publishEvent(capability, event);
  await serializeReplica(async () => {
    const journal = await loadJournal(capability, snapshot);
    journal.pending = journal.pending.filter(id => id !== event.eventId);
    await saveJournal(capability.boardId, journal);
  });
  return result;
}

async function buildLocalOperation(
  capability: RoamingCapability,
  operation: LocalOperation,
  snapshot: LocalBoardSnapshot,
  logicalClock: number,
): Promise<RoamingBoardEvent> {
  if (!capability.canWrite) {
    throw new Error('Гостевой доступ не разрешает изменять доску.');
  }
  if (operation.kind === 'board.appearance.update') {
    const { replicaId } = await identity();
    return {
      protocolVersion: ROAMING_PROTOCOL_VERSION,
      eventId: operation.id,
      workspaceId: capability.workspaceId,
      boardId: capability.boardId,
      capabilityEpoch: capability.capabilityEpoch,
      replicaId,
      replicaSeq: logicalClock,
      logicalClock,
      entityType: 'board',
      entityId: capability.boardId,
      operation: 'board.appearance.put',
      fieldMask: fieldsFor(operation),
      payload: { appearance: operation.payload.optimistic },
      occurredAt: operation.createdAt,
    };
  }
  const cardId = operationCardId(operation);
  const card = operation.kind === 'card.delete'
    ? operation.payload.card
    : snapshot.cards.find((candidate) => candidate.id === cardId);
  if (!card) throw new Error('Локальная карточка для события не найдена.');
  const { replicaId } = await identity();
  return eventForCard({
    capability,
    operation,
    card,
    checklists: snapshot.checklistsByCardId[card.id] || [],
    replicaId,
    replicaSeq: logicalClock,
    logicalClock,
  });
}

/** Commit locally before attempting transport. Same event and clock on every retry. */
export async function commitLocalOperation(
  capability: RoamingCapability,
  operation: LocalOperation,
  snapshot: LocalBoardSnapshot,
  previousSnapshot: LocalBoardSnapshot = snapshot,
  recoverLegacy = false,
) {
  return serializeReplica(async () => {
    let journal = await loadJournal(capability, previousSnapshot);
    const existing = journal.events.find(event => event.eventId === operation.id || event.payload._replacesLocalOperation === operation.id);
    if (existing) return existing;
    const logicalClock = Math.max(Date.now() * 1000, journal.clock + 1);
    const event = await buildLocalOperation(capability, recoverLegacy ? {...operation,id:Crypto.randomUUID()} : operation, snapshot, logicalClock);
    event.payload.activity = operationActivity(operation,event);
    if (recoverLegacy) event.payload._replacesLocalOperation = operation.id;
    journal = mergeJournal(journal, [event]);
    journal.pending.push(event.eventId);
    await saveJournal(capability.boardId, journal);
    return event;
  });
}

export async function publishLocalOperation(
  capability: RoamingCapability, operation: LocalOperation, snapshot: LocalBoardSnapshot,
) {
  const event = await commitLocalOperation(capability, operation, snapshot);
  const result = await publishEvent(capability, event);
  await serializeReplica(async () => {
    const journal = await loadJournal(capability, snapshot);
    journal.pending = journal.pending.filter(id => id !== event.eventId);
    await saveJournal(capability.boardId, journal);
  });
  return result;
}

export async function recoverLocalReplica(capability: RoamingCapability, snapshot: LocalBoardSnapshot | null) {
  return serializeReplica(async () => projectJournal(await loadJournal(capability, snapshot)).snapshot);
}

export async function publishedOperationIds(capability: RoamingCapability) {
  return serializeReplica(async () => {
    const journal = await loadJournal(capability, null);
    return new Set(journal.events.filter(event => !journal.pending.includes(event.eventId)).flatMap(event =>
      [event.eventId, ...(typeof event.payload._replacesLocalOperation === 'string' ? [event.payload._replacesLocalOperation] : [])]));
  });
}

// Journal delivery survives a crash between journal commit and UI queue update.
export async function flushReplicaJournal(capability: RoamingCapability) {
  const pending = await serializeReplica(async () => {
    const journal = await loadJournal(capability, null);
    return journal.events.filter(event => journal.pending.includes(event.eventId));
  });
  for (const event of pending) {
    await publishEvent(capability, event);
    await serializeReplica(async () => {
      const journal = await loadJournal(capability, null);
      journal.pending = journal.pending.filter(id => id !== event.eventId);
      await saveJournal(capability.boardId, journal);
    });
  }
}

export async function pullRoamingBoard(
  capability: RoamingCapability,
  currentSnapshot: LocalBoardSnapshot | null,
): Promise<RoamingPullResult> {
  const boardKey = validateCapability(capability);
  const response = await fetchFromRelays({
    relays: capability.relays,
    kind: capability.eventKind,
    boardTag: capability.boardTag,
  });
  const events = response.events.flatMap((nostr) => {
    try {
      const event = openRoamingEvent(nostr.content, boardKey, capability.boardTag);
      if (!Number.isSafeInteger(event.logicalClock) || event.logicalClock < 0) return [];
      const knownWriter = capability.writerPublicKeys.includes(nostr.pubkey.toLowerCase());
      const proof = event.payload._deviceDelegation;
      if (!knownWriter && proof) {
        // Validate authority at signing time: a peer may receive stored work later.
        const {root, grant} = verifyReplicationChain(proof as import('nostr-tools/pure').Event[], nostr.pubkey, nostr.created_at);
        if (!capability.delegationRoots?.includes(root) || grant.boardId !== capability.boardId
          || grant.workspaceId !== capability.workspaceId || grant.epoch !== capability.capabilityEpoch) return [];
      } else if (!knownWriter && (capability.writerPublicKeys.length || capability.capabilityEpoch > 1)) return [];
      if (event.workspaceId !== capability.workspaceId || event.boardId !== capability.boardId
        || event.capabilityEpoch !== capability.capabilityEpoch) return [];
      return [event];
    } catch { return []; }
  });
  return serializeReplica(async () => {
    let journal = await loadJournal(capability, currentSnapshot);
    journal = mergeJournal(journal, events);
    const merged = projectJournal(journal);
    await saveJournal(capability.boardId, journal);
    return {
      snapshot: merged.snapshot,
      applyState: { ...merged.state, lastRelayPullAt: Math.floor(Date.now() / 1000) },
      received: events.length, applied: merged.applied, relayCount: response.relayCount,
    };
  });
}

export { loadRoamingCapability };
