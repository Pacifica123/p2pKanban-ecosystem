import * as Crypto from 'expo-crypto';
import {useAuth} from '../auth/AuthProvider';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, InteractionManager } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import { ApiError, getApiNodeOrigin, isNetworkError } from '../../shared/api/client';
import { isPrivateNodeOrigin } from '../connection/connection';
import {
  applyLocalCardVisibility,
  hideCardOnThisDevice,
  loadLocallyHiddenCards,
  pruneLocallyHiddenCards,
  reconcileHiddenCardsWithCoordinator,
  restoreCardOnThisDevice,
  type LocallyHiddenCard,
} from './localVisibility';
import {
  archiveCard as archiveCardRemote,
  createCard as createCardRemote,
  createChecklist as createChecklistRemote,
  createChecklistItem as createChecklistItemRemote,
  deleteCard as deleteCardRemote,
  deleteChecklist as deleteChecklistRemote,
  deleteChecklistItem as deleteChecklistItemRemote,
  moveCard as moveCardRemote,
  provisionRoamingBoard,
  unarchiveCard as unarchiveCardRemote,
  updateBoardAppearance as updateBoardAppearanceRemote,
  updateCard as updateCardRemote,
  updateChecklist as updateChecklistRemote,
  updateChecklistItem as updateChecklistItemRemote,
} from '../../shared/api/endpoints';
import type {
  Card,
  Checklist,
  ChecklistItem,
  UpdateBoardAppearanceRequest,
} from '../../shared/types/api';
import {
  getRoamingAuthorPublicKey,
  installRoamingCapability,
  loadRoamingCapability,
  publishBoardSnapshot,
  commitLocalOperation,
  flushReplicaJournal,
  recoverLocalReplica,
  publishedOperationIds,
  pullRoamingBoard,
} from '../roaming/service';
import { resetRoamingApplyState } from '../roaming/storage';
import type { RoamingCapability } from '../roaming/types';
import { touchWorkspaceSync } from '../sync/syncService';
import {
  applyOperation,
  applyOperations,
  createTemporaryCard,
  createTemporaryChecklist,
  createTemporaryChecklistItem,
  isChecklistOperation,
  isTemporaryCardId,
  isTemporaryChecklistId,
  isTemporaryChecklistItemId,
  mergeBoardSnapshots,
  operationAffectsCard,
  operationCardId,
  replaceChecklist,
  replaceChecklistItem,
  replaceCreatedCard,
  replaceCreatedChecklist,
  replaceCreatedChecklistItem,
  type LocalBoardSnapshot,
  type LocalOperation,
} from './model';
import {
  loadLocalBoardState,
  loadOperationQueue,
  persistBoardAndQueue,
  persistServerSnapshot,
  serializeLocalState,
} from './repository';
import { fetchBoardSnapshot } from './snapshot';
import { moveCardReminder } from '../reminders/service';
import {
  hasPendingPublication,
} from './delivery';

export interface LocalBoardRuntime {
  snapshot: LocalBoardSnapshot | null;
  hydrated: boolean;
  refreshing: boolean;
  flushing: boolean;
  pendingCount: number;
  relayPendingCount: number;
  failedCount: number;
  canEdit: boolean;
  syncMode: 'node' | 'roaming';
  relayCount: number;
  lastError: string | null;
  refresh: () => Promise<void>;
  retryFailed: () => Promise<void>;
  createCard: (input: {
    title: string;
    description?: string;
    columnId: string;
    priority?: Card['priority'];
  }) => Promise<Card>;
  updateAppearance: (input: UpdateBoardAppearanceRequest) => Promise<void>;
  updateCard: (cardId: string, input: Partial<Pick<
    Card,
    'title' | 'description' | 'priority' | 'startAt' | 'dueAt'
  >>) => Promise<void>;
  moveCard: (
    cardId: string,
    targetColumnId: string,
    position?: number | null,
  ) => Promise<void>;
  archiveCard: (cardId: string) => Promise<void>;
  unarchiveCard: (cardId: string) => Promise<void>;
  deleteCard: (cardId: string) => Promise<void>;
  locallyHiddenCards: Card[];
  hideCardLocally: (cardId: string) => Promise<void>;
  restoreCardLocally: (cardId: string) => Promise<void>;
  mergeCoordinatorCard: (card: Card) => Promise<void>;
  getCardChecklists: (cardId: string) => Checklist[];
  createChecklist: (cardId: string, title: string) => Promise<void>;
  updateChecklist: (cardId: string, checklistId: string, title: string) => Promise<void>;
  deleteChecklist: (cardId: string, checklistId: string) => Promise<void>;
  createChecklistItem: (
    cardId: string,
    checklistId: string,
    title: string,
  ) => Promise<void>;
  updateChecklistItem: (
    cardId: string,
    checklistId: string,
    itemId: string,
    input: { title?: string; position?: number | null; isDone?: boolean | null },
  ) => Promise<void>;
  deleteChecklistItem: (
    cardId: string,
    checklistId: string,
    itemId: string,
  ) => Promise<void>;
  toggleChecklistItem: (
    cardId: string,
    checklistId: string,
    itemId: string,
    isDone: boolean,
  ) => Promise<void>;
  cardOperationState: (cardId: string) => 'pending' | 'failed' | null;
}

function now() {
  return new Date().toISOString();
}

function operationBase(boardId: string, entityId: string, accessEpoch: number) {
  return {
    id: Crypto.randomUUID(),
    boardId,
    entityId,
    status: 'pending' as const,
    accessEpoch,
    createdAt: now(),
    attempts: 0,
    lastError: null,
  };
}

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Не удалось синхронизировать изменения.';
}

function coordinatorUnavailable(error: unknown) {
  return isNetworkError(error)
    || (error instanceof ApiError && [408, 502, 503, 504].includes(error.status));
}

function canPublishThroughRoaming(operation: LocalOperation) {
  if (isTemporaryCardId(operationCardId(operation))) return false;
  if (isTemporaryChecklistId(operation.entityId)) return false;
  if (isTemporaryChecklistItemId(operation.entityId)) return false;
  if (
    isChecklistOperation(operation)
    && 'checklistId' in operation.payload
    && isTemporaryChecklistId(operation.payload.checklistId)
  ) return false;
  return true;
}

function replaceCardInSnapshot(snapshot: LocalBoardSnapshot, card: Card) {
  return {
    ...snapshot,
    cards: snapshot.cards.map((candidate) => candidate.id === card.id ? card : candidate),
    cachedAt: card.updatedAt,
  };
}

function removeCardFromSnapshot(snapshot: LocalBoardSnapshot, cardId: string) {
  const checklistsByCardId = { ...snapshot.checklistsByCardId };
  delete checklistsByCardId[cardId];
  return {
    ...snapshot,
    cards: snapshot.cards.filter((card) => card.id !== cardId),
    checklistsByCardId,
    cachedAt: now(),
  };
}

function nextCardPosition(snapshot: LocalBoardSnapshot, columnId: string, cardId: string) {
  return snapshot.cards
    .filter((card) => card.columnId === columnId && card.id !== cardId && !card.isArchived)
    .reduce((highest, card) => Math.max(highest, card.position), 0) + 1000;
}

export function useLocalBoard(
  boardId: string,
  workspaceId: string,
  accessEpoch = 1,
  canEdit = true,
): LocalBoardRuntime {
  const { isOnline, networkType } = useNetwork();
  const {user} = useAuth();
  const preferRoaming = networkType === 'cellular'
    && isPrivateNodeOrigin(getApiNodeOrigin());
  const [snapshot, setSnapshot] = useState<LocalBoardSnapshot | null>(null);
  const [operations, setOperations] = useState<LocalOperation[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [flushing, setFlushing] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [syncMode, setSyncMode] = useState<'node' | 'roaming'>('node');
  const [relayCount, setRelayCount] = useState(0);
  const [locallyHidden, setLocallyHidden] = useState<LocallyHiddenCard[]>([]);
  const snapshotRef = useRef<LocalBoardSnapshot | null>(null);
  const operationsRef = useRef<LocalOperation[]>([]);
  const roamingCapabilityRef = useRef<RoamingCapability | null>(null);
  const flushLock = useRef(false);
  const refreshLock = useRef(false);
  const nodeUnavailableUntilRef = useRef(0);
  const initialSyncTaskRef = useRef<ReturnType<
    typeof InteractionManager.runAfterInteractions
  > | null>(null);

  const currentAccessEpoch = useCallback(() => Math.max(
    accessEpoch,
    roamingCapabilityRef.current?.capabilityEpoch || 1,
  ), [accessEpoch]);

  const runSerialized = useCallback(serializeLocalState, []);

  const applyState = useCallback((
    nextSnapshot: LocalBoardSnapshot | null,
    nextOperations: LocalOperation[],
  ) => {
    snapshotRef.current = nextSnapshot;
    operationsRef.current = nextOperations;
    setSnapshot(nextSnapshot);
    setOperations(nextOperations.filter((operation) => operation.boardId === boardId));
  }, [boardId]);

  const refresh = useCallback(async () => {
    if (!isOnline || refreshLock.current) return;
    refreshLock.current = true;
    setRefreshing(true);
    setLastError(null);
    let relaySucceeded = false;
    let relayReceived = 0;
    let relayFailure: unknown = null;
    let relaySnapshot: LocalBoardSnapshot | null = null;
    let relayApplyState: Awaited<ReturnType<typeof pullRoamingBoard>>['applyState'] | undefined;
    try {
      const installed = roamingCapabilityRef.current || await loadRoamingCapability(boardId);
      if (installed) {
        roamingCapabilityRef.current = installed;
        const relay = await pullRoamingBoard(installed, snapshotRef.current);
        await runSerialized(async () => {
          const recovered = await recoverLocalReplica(installed, snapshotRef.current);
          const hidden = await pruneLocallyHiddenCards(boardId, Object.keys(relay.applyState.tombstones || {}));
          setLocallyHidden(hidden);
          if (recovered) {
            const visible = applyLocalCardVisibility(recovered, hidden);
            const queue = await loadOperationQueue();
            await persistBoardAndQueue(visible, queue);
            applyState(visible, queue);
          }
        });
        setSyncMode('roaming'); setRelayCount(relay.relayCount);
        return;
      }
      await runSerialized(async () => {
        const storedCapability = roamingCapabilityRef.current
          || await loadRoamingCapability(boardId);
        if (storedCapability) {
          roamingCapabilityRef.current = storedCapability;
          try {
            const relay = await pullRoamingBoard(storedCapability, snapshotRef.current);
            relayReceived = relay.received;
            relaySnapshot = relay.snapshot;
            relayApplyState = relay.applyState;
            const nextHidden = await pruneLocallyHiddenCards(
              boardId,
              Object.keys(relay.applyState.tombstones || {}),
            );
            setLocallyHidden(nextHidden);
            if (relay.snapshot) {
              const visibleRelaySnapshot = applyLocalCardVisibility(relay.snapshot, nextHidden);
              const queued = await loadOperationQueue();
              await persistBoardAndQueue(visibleRelaySnapshot, queued);
              applyState(visibleRelaySnapshot, queued);
              relaySnapshot = visibleRelaySnapshot;
            }
            setSyncMode('roaming');
            setRelayCount(relay.relayCount);
            relaySucceeded = true;
          } catch (error) {
            relayFailure = error;
          }
        }

        // A provisioned replica reads the journal. HTTP is only initial enrollment.
        if (storedCapability) {
          if (relayFailure) throw relayFailure;
          return;
        }

        try {
          await touchWorkspaceSync(workspaceId).catch(() => null);
          const capabilityPromise = getRoamingAuthorPublicKey()
            .then((authorPublicKey) => provisionRoamingBoard(boardId, authorPublicKey))
            .catch(() => null);
          const [coordinatorSnapshot, allOperations, provisionedCapability] = await Promise.all([
            fetchBoardSnapshot(boardId, workspaceId),
            loadOperationQueue(),
            capabilityPromise,
          ]);
          const previousCapability = roamingCapabilityRef.current;
          if (provisionedCapability) {
            const rotated = Boolean(previousCapability && (
              previousCapability.capabilityEpoch !== provisionedCapability.capabilityEpoch
              || previousCapability.boardTag !== provisionedCapability.boardTag
            ));
            if (rotated) {
              relaySnapshot = null;
              relayApplyState = undefined;
              relayReceived = 0;
              await resetRoamingApplyState(boardId);
            }
            await installRoamingCapability(provisionedCapability);
            roamingCapabilityRef.current = provisionedCapability;
            setSyncMode('roaming');
            setRelayCount(provisionedCapability.relays.length);
            relaySucceeded = true;
          }
          const remainingOperations = allOperations;
          const nextHidden = await reconcileHiddenCardsWithCoordinator(
            boardId,
            coordinatorSnapshot.cards.map((card) => card.id),
          );
          setLocallyHidden(nextHidden);
          const seeded = applyLocalCardVisibility(coordinatorSnapshot, nextHidden);
          nodeUnavailableUntilRef.current = 0;
          const mergedBase = mergeBoardSnapshots(seeded, relaySnapshot, relayApplyState);
          const merged = await persistServerSnapshot(mergedBase, remainingOperations);
          applyState(merged, remainingOperations);

          if (provisionedCapability?.canWrite && relayReceived === 0) {
            await publishBoardSnapshot(provisionedCapability, merged);
          }
        } catch (error) {
          if (coordinatorUnavailable(error)) {
            nodeUnavailableUntilRef.current = Date.now() + 30_000;
          }
          if (!relaySucceeded) throw error;
        }
      });
    } catch (error) {
      setLastError(message(relayFailure || error));
    } finally {
      refreshLock.current = false;
      setRefreshing(false);
    }
  }, [applyState, boardId, isOnline, preferRoaming, networkType, runSerialized, workspaceId]);

  const flush = useCallback(async () => {
    if (!isOnline || flushLock.current) return;
    flushLock.current = true;
    setFlushing(true);
    setLastError(null);

    try {
      const installed = roamingCapabilityRef.current || await loadRoamingCapability(boardId);
      if (installed) {
        roamingCapabilityRef.current = installed;
        // Commit legacy pending intentions locally; transport never holds the UI storage lock.
        await runSerialized(async () => {
          let local = snapshotRef.current;
          if (!local) return;
          let queue = await loadOperationQueue();
          for (const initial of queue.filter(op => op.boardId === boardId && op.status !== 'failed')) {
            let operation = queue.find(op => op.id === initial.id)!;
            if ((operation.accessEpoch || 1) !== installed.capabilityEpoch) {
              queue = queue.map(op => op.id === operation.id ? {...op, status:'failed',lastError:'Изменилось поколение доступа; требуется обновлённый capability.'} : op);
              continue;
            }
            let replacement: {snapshot: LocalBoardSnapshot; operations: LocalOperation[]} | null = null;
            if (operation.kind === 'card.create' && isTemporaryCardId(operation.entityId)) {
              replacement = replaceCreatedCard(local, queue, operation.entityId,
                {...(local.cards.find(card => card.id === operation.entityId) || operation.payload.tempCard),id:Crypto.randomUUID()});
            } else if (operation.kind === 'checklist.create' && isTemporaryChecklistId(operation.entityId)) {
              replacement = replaceCreatedChecklist(local, queue, operation.payload.cardId, operation.entityId,
                {...operation.payload.tempChecklist,id:Crypto.randomUUID()});
            } else if (operation.kind === 'checklist.item.create' && isTemporaryChecklistItemId(operation.entityId)) {
              replacement = replaceCreatedChecklistItem(local, queue, operation.payload.cardId, operation.entityId,
                {...operation.payload.tempItem,id:Crypto.randomUUID()});
            }
            if (replacement) {
              local = replacement.snapshot; queue = replacement.operations;
              operation = queue.find(op => op.id === initial.id)!;
            }
            if (canPublishThroughRoaming(operation)) await commitLocalOperation(installed, operation, local, local, true);
          }
          await persistBoardAndQueue(local, queue);
          applyState(local, queue);
        });
        try { await flushReplicaJournal(installed); }
        catch (error) { setLastError(message(error)); }
        await runSerialized(async () => {
          const local = snapshotRef.current;
          if (!local) return;
          const delivered = await publishedOperationIds(installed);
          const queue = (await loadOperationQueue()).filter(op => op.boardId !== boardId || !delivered.has(op.id));
          await persistBoardAndQueue(local, queue);
          applyState(local, queue);
        });
        setSyncMode('roaming'); setRelayCount(installed.relays.length);
        return;
      }
      await runSerialized(async () => {
        let allOperations = await loadOperationQueue();
        const initialSnapshot = snapshotRef.current;
        if (!initialSnapshot) return;
        let currentSnapshot: LocalBoardSnapshot = initialSnapshot;
        const boardOperations = allOperations
          .filter((operation) => operation.boardId === boardId
            && hasPendingPublication(operation))
          .sort((left, right) => left.createdAt.localeCompare(right.createdAt));

        for (const queuedOperation of boardOperations) {
          const current = allOperations.find((candidate) => candidate.id === queuedOperation.id);
          if (!current || !hasPendingPublication(current)) continue;

          const capability = roamingCapabilityRef.current
            || await loadRoamingCapability(boardId);
          if (capability) roamingCapabilityRef.current = capability;
          const activeEpoch = currentAccessEpoch();
          if ((current.accessEpoch || 1) !== activeEpoch) {
            const errorText = 'Отложенное изменение относится к отозванному поколению доступа и не будет применено.';
            allOperations = allOperations.map((candidate) => candidate.id === current.id
              ? {
                ...candidate,
                status: 'failed',
                attempts: candidate.attempts + 1,
                lastError: errorText,
              }
              : candidate);
            await persistBoardAndQueue(currentSnapshot, allOperations);
            applyState(currentSnapshot, allOperations);
            setLastError(errorText);
            continue;
          }

          if (capability) break; // Enrollment raced this REST pass; next flush uses the journal.
          if (current.status === 'relay_pending') {
            setLastError('Для восстановления старой очереди нужен сохранённый ключ доски.');
            break;
          }

          try {
            let nextSnapshot: LocalBoardSnapshot = currentSnapshot;
            let nextOperations = allOperations;

            if (current.kind === 'board.appearance.update') {
              const saved = await updateBoardAppearanceRemote(
                boardId,
                current.payload.input,
              );
              nextSnapshot = {
                ...nextSnapshot,
                appearance: saved,
                cachedAt: saved.updatedAt || now(),
              };
            } else if (current.kind === 'card.create') {
              const created = await createCardRemote(boardId, current.payload.input);
              const replaced = replaceCreatedCard(
                nextSnapshot,
                nextOperations,
                current.entityId,
                created,
              );
              nextSnapshot = replaced.snapshot;
              nextOperations = replaced.operations;
              await moveCardReminder(current.entityId, created.id, created.title);
            } else if (current.kind === 'card.update') {
              const updated = await updateCardRemote(current.entityId, current.payload.input);
              nextSnapshot = replaceCardInSnapshot(nextSnapshot, updated);
            } else if (current.kind === 'card.move') {
              const moved = await moveCardRemote(current.entityId, current.payload.input);
              nextSnapshot = replaceCardInSnapshot(nextSnapshot, moved);
            } else if (current.kind === 'card.archive') {
              const archived = await archiveCardRemote(current.entityId);
              nextSnapshot = replaceCardInSnapshot(nextSnapshot, archived);
            } else if (current.kind === 'card.unarchive') {
              const restored = await unarchiveCardRemote(current.entityId);
              nextSnapshot = replaceCardInSnapshot(nextSnapshot, restored);
            } else if (current.kind === 'card.delete') {
              await deleteCardRemote(current.entityId);
              nextSnapshot = removeCardFromSnapshot(nextSnapshot, current.entityId);
            } else if (current.kind === 'checklist.create') {
              const created = await createChecklistRemote(
                current.payload.cardId,
                current.payload.input,
              );
              const replaced = replaceCreatedChecklist(
                nextSnapshot,
                nextOperations,
                current.payload.cardId,
                current.entityId,
                created,
              );
              nextSnapshot = replaced.snapshot;
              nextOperations = replaced.operations;
            } else if (current.kind === 'checklist.update') {
              const updated = await updateChecklistRemote(
                current.entityId,
                current.payload.input,
              );
              nextSnapshot = replaceChecklist(nextSnapshot, current.payload.cardId, updated);
            } else if (current.kind === 'checklist.delete') {
              await deleteChecklistRemote(current.entityId);
            } else if (current.kind === 'checklist.item.create') {
              const created = await createChecklistItemRemote(
                current.payload.checklistId,
                current.payload.input,
              );
              const replaced = replaceCreatedChecklistItem(
                nextSnapshot,
                nextOperations,
                current.payload.cardId,
                current.entityId,
                created,
              );
              nextSnapshot = replaced.snapshot;
              nextOperations = replaced.operations;
            } else if (current.kind === 'checklist.item.update') {
              const updated = await updateChecklistItemRemote(
                current.entityId,
                current.payload.input,
              );
              nextSnapshot = replaceChecklistItem(
                nextSnapshot,
                current.payload.cardId,
                updated,
              );
            } else {
              await deleteChecklistItemRemote(current.entityId);
            }

            nodeUnavailableUntilRef.current = 0;
            nextOperations = nextOperations.filter((candidate) => candidate.id !== current.id);
            nextSnapshot = applyOperations(
              nextSnapshot,
              nextOperations.filter((operation) => operation.boardId === boardId),
            );
            currentSnapshot = nextSnapshot;
            allOperations = nextOperations;
            await persistBoardAndQueue(currentSnapshot, allOperations);
            applyState(currentSnapshot, allOperations);

          } catch (error) {
            if (coordinatorUnavailable(error)) {
              nodeUnavailableUntilRef.current = Date.now() + 30_000;
              setLastError('Узел недоступен; для relay требуется первоначальная подготовка доски.');
              break;
            }

            const errorText = error instanceof ApiError && error.status === 403
              ? 'Изменение больше не разрешено. Проверьте доступ к пространству.'
              : message(error);
            allOperations = allOperations.map((candidate) => candidate.id === current.id
              ? {
                ...candidate,
                status: 'failed',
                attempts: candidate.attempts + 1,
                lastError: errorText,
              }
              : candidate);
            await persistBoardAndQueue(currentSnapshot, allOperations);
            applyState(currentSnapshot, allOperations);
            setLastError(errorText);
          }
        }
      });
    } finally {
      flushLock.current = false;
      setFlushing(false);
    }
  }, [applyState, boardId, currentAccessEpoch, isOnline, preferRoaming, runSerialized]);

  useEffect(() => {
    let active = true;
    setHydrated(false);
    void Promise.all([
      loadLocalBoardState(boardId),
      loadRoamingCapability(boardId),
      loadLocallyHiddenCards(boardId),
    ]).then(async ([local, capability, hidden]) => {
      if (capability) local.snapshot = await recoverLocalReplica(capability, local.snapshot);
      if (!active) return;
      setLocallyHidden(hidden);
      roamingCapabilityRef.current = capability;
      if (capability) {
        setSyncMode('roaming');
        setRelayCount(capability.relays.length);
      }
      applyState(
        local.snapshot ? applyLocalCardVisibility(local.snapshot, hidden) : null,
        local.operations,
      );
      setHydrated(true);
      if (isOnline) {
        const hasPending = local.operations.some(hasPendingPublication);
        initialSyncTaskRef.current = InteractionManager.runAfterInteractions(() => {
          initialSyncTaskRef.current = null;
          if (!active) return;
          if (hasPending) {
            void flush().then(() => active ? refresh() : undefined);
          } else {
            void refresh();
          }
        });
      }
    });
    return () => {
      active = false;
      initialSyncTaskRef.current?.cancel();
      initialSyncTaskRef.current = null;
    };
  }, [applyState, boardId, flush, isOnline, refresh]);

  useEffect(() => {
    if (isOnline && operations.some(hasPendingPublication)) {
      void flush();
    }
  }, [flush, isOnline, operations]);

  useEffect(() => {
    if (!isOnline || !hydrated) return;
    let active = AppState.currentState === 'active';
    const synchronize = () => {
      if (active) void flush().then(() => refresh()).catch(error => setLastError(message(error)));
    };
    const timer = setInterval(synchronize, 15_000);
    const subscription = AppState.addEventListener('change', state => {
      active = state === 'active';
      if (active) synchronize();
    });
    return () => { clearInterval(timer); subscription.remove(); };
  }, [flush, refresh, hydrated, isOnline]);

  const enqueue = useCallback(async (operation: LocalOperation) => {
    operation = {...operation,actor:{userId:user?.id || null,displayName:user?.displayName || null}};
    if (!canEdit) throw new Error('Гостевой доступ разрешает только чтение доски.');
    const currentSnapshot = snapshotRef.current;
    if (!currentSnapshot) throw new Error('Доска ещё не загружена.');
    await runSerialized(async () => {
      const allOperations = await loadOperationQueue();
      const nextOperations = [...allOperations, operation];
      const nextSnapshot = applyOperation(snapshotRef.current || currentSnapshot, operation);
      const capability = roamingCapabilityRef.current || await loadRoamingCapability(boardId);
      if (capability && canPublishThroughRoaming(operation)) {
        await commitLocalOperation(capability, operation, nextSnapshot, snapshotRef.current || currentSnapshot);
      }
      await persistBoardAndQueue(nextSnapshot, nextOperations);
      applyState(nextSnapshot, nextOperations);
    });
    if (isOnline) void flush();
  }, [applyState, canEdit, flush, isOnline, runSerialized, user]);

  const retryFailed = useCallback(async () => {
    const currentSnapshot = snapshotRef.current;
    if (!currentSnapshot) return;
    await runSerialized(async () => {
      const allOperations = await loadOperationQueue();
      const next = allOperations.map((operation) =>
        operation.boardId === boardId && operation.status === 'failed'
          ? { ...operation, status: 'pending' as const, lastError: null }
          : operation);
      const latestSnapshot = snapshotRef.current || currentSnapshot;
      await persistBoardAndQueue(latestSnapshot, next);
      applyState(latestSnapshot, next);
    });
    nodeUnavailableUntilRef.current = 0;
    await flush();
  }, [applyState, boardId, flush, runSerialized]);

  const pendingCount = operations.filter((operation) => operation.status === 'pending').length;
  const relayPendingCount = operations
    .filter((operation) => operation.status === 'relay_pending').length;
  const failedCount = operations.filter((operation) => operation.status === 'failed').length;

  return useMemo(() => ({
    snapshot,
    hydrated,
    refreshing,
    flushing,
    pendingCount,
    relayPendingCount,
    failedCount,
    canEdit,
    syncMode,
    relayCount,
    lastError,
    refresh,
    retryFailed,
    createCard: async (input) => {
      if (!snapshotRef.current) throw new Error('Доска ещё не загружена.');
      const createdAt = now();
      const tempCard = createTemporaryCard({
        id: roamingCapabilityRef.current
          ? Crypto.randomUUID()
          : `local-card-${Crypto.randomUUID()}`,
        boardId,
        columnId: input.columnId,
        title: input.title,
        description: input.description,
        priority: input.priority,
        cards: snapshotRef.current.cards,
        now: createdAt,
      });
      await enqueue({
        ...operationBase(boardId, tempCard.id, currentAccessEpoch()),
        createdAt,
        kind: 'card.create',
        payload: { input, tempCard },
      });
      return tempCard;
    },
    updateAppearance: async (input) => {
      const current = snapshotRef.current;
      if (!current) throw new Error('Доска ещё не загружена.');
      const timestamp = now();
      await enqueue({
        ...operationBase(boardId, boardId, currentAccessEpoch()),
        createdAt: timestamp,
        kind: 'board.appearance.update',
        payload: {
          input,
          optimistic: {
            ...current.appearance,
            ...input,
            wallpaper: input.wallpaper || current.appearance.wallpaper,
            customProperties: input.customProperties || current.appearance.customProperties,
            isCustomized: true,
            updatedAt: timestamp,
          },
        },
      });
    },
    updateCard: async (cardId, input) => enqueue({
      ...operationBase(boardId, cardId, currentAccessEpoch()),
      kind: 'card.update',
      payload: { input },
    }),
    moveCard: async (cardId, targetColumnId, position) => {
      const current = snapshotRef.current;
      if (!current) throw new Error('Доска ещё не загружена.');
      await enqueue({
        ...operationBase(boardId, cardId, currentAccessEpoch()),
        kind: 'card.move',
        payload: {
          input: {
            targetColumnId,
            position: position ?? nextCardPosition(current, targetColumnId, cardId),
          },
        },
      });
    },
    archiveCard: async (cardId) => enqueue({
      ...operationBase(boardId, cardId, currentAccessEpoch()),
      kind: 'card.archive',
      payload: {},
    }),
    unarchiveCard: async (cardId) => enqueue({
      ...operationBase(boardId, cardId, currentAccessEpoch()),
      kind: 'card.unarchive',
      payload: {},
    }),
    deleteCard: async (cardId) => {
      const current = snapshotRef.current;
      if (!current) return;
      const card = current.cards.find((candidate) => candidate.id === cardId);
      if (!card) return;
      const allOperations = await loadOperationQueue();
      const isUnsyncedCreate = allOperations.some((operation) =>
        operation.kind === 'card.create' && operation.entityId === cardId && !roamingCapabilityRef.current);
      if (!isUnsyncedCreate) {
        if (!roamingCapabilityRef.current && allOperations.some((operation) => operationAffectsCard(operation, cardId))) {
          throw new Error('Сначала дождитесь синхронизации изменений этой карточки.');
        }
        await enqueue({
          ...operationBase(boardId, cardId, currentAccessEpoch()),
          kind: 'card.delete',
          payload: { card },
        });
        return;
      }
      await runSerialized(async () => {
        const latestOperations = await loadOperationQueue();
        const nextOperations = latestOperations.filter((operation) =>
          !operationAffectsCard(operation, cardId));
        const nextSnapshot = removeCardFromSnapshot(
          snapshotRef.current || current,
          cardId,
        );
        await persistBoardAndQueue(nextSnapshot, nextOperations);
        applyState(nextSnapshot, nextOperations);
      });
    },
    locallyHiddenCards: locallyHidden.map((value) => value.card),
    hideCardLocally: async (cardId) => {
      const current = snapshotRef.current;
      if (!current) return;
      const allOperations = await loadOperationQueue();
      if (allOperations.some((operation) => operationAffectsCard(operation, cardId))) {
        throw new Error('Сначала дождитесь синхронизации изменений этой карточки.');
      }
      await runSerialized(async () => {
        const result = await hideCardOnThisDevice(
          boardId,
          snapshotRef.current || current,
          cardId,
        );
        setLocallyHidden(result.hidden);
        await persistBoardAndQueue(result.snapshot, allOperations);
        applyState(result.snapshot, allOperations);
      });
    },
    restoreCardLocally: async (cardId) => {
      const current = snapshotRef.current;
      if (!current) return;
      await runSerialized(async () => {
        const allOperations = await loadOperationQueue();
        const result = await restoreCardOnThisDevice(
          boardId,
          snapshotRef.current || current,
          cardId,
        );
        setLocallyHidden(result.hidden);
        await persistBoardAndQueue(result.snapshot, allOperations);
        applyState(result.snapshot, allOperations);
      });
      if (isOnline) void refresh();
    },
    mergeCoordinatorCard: async (card) => {
      const current = snapshotRef.current;
      if (!current) return;
      await runSerialized(async () => {
        const allOperations = await loadOperationQueue();
        const nextSnapshot = applyOperations(
          replaceCardInSnapshot(snapshotRef.current || current, card),
          allOperations.filter((operation) => operation.boardId === boardId),
        );
        await persistBoardAndQueue(nextSnapshot, allOperations);
        applyState(nextSnapshot, allOperations);
      });
    },
    getCardChecklists: (cardId) => snapshotRef.current?.checklistsByCardId[cardId] || [],
    createChecklist: async (cardId, title) => {
      const current = snapshotRef.current;
      if (!current) throw new Error('Доска ещё не загружена.');
      const createdAt = now();
      const tempChecklist = createTemporaryChecklist({
        id: roamingCapabilityRef.current
          ? Crypto.randomUUID()
          : `local-checklist-${Crypto.randomUUID()}`,
        cardId,
        title,
        checklists: current.checklistsByCardId[cardId] || [],
        now: createdAt,
      });
      await enqueue({
        ...operationBase(boardId, tempChecklist.id, currentAccessEpoch()),
        createdAt,
        kind: 'checklist.create',
        payload: {
          cardId,
          input: { title, position: tempChecklist.position },
          tempChecklist,
        },
      });
    },
    updateChecklist: async (cardId, checklistId, title) => enqueue({
      ...operationBase(boardId, checklistId, currentAccessEpoch()),
      kind: 'checklist.update',
      payload: { cardId, input: { title } },
    }),
    deleteChecklist: async (cardId, checklistId) => enqueue({
      ...operationBase(boardId, checklistId, currentAccessEpoch()),
      kind: 'checklist.delete',
      payload: { cardId },
    }),
    createChecklistItem: async (cardId, checklistId, title) => {
      const current = snapshotRef.current;
      if (!current) throw new Error('Доска ещё не загружена.');
      const checklist = (current.checklistsByCardId[cardId] || [])
        .find((candidate) => candidate.id === checklistId);
      if (!checklist) throw new Error('Чек-лист не найден.');
      const createdAt = now();
      const tempItem = createTemporaryChecklistItem({
        id: roamingCapabilityRef.current
          ? Crypto.randomUUID()
          : `local-checklist-item-${Crypto.randomUUID()}`,
        checklistId,
        title,
        items: checklist.items,
        now: createdAt,
      });
      await enqueue({
        ...operationBase(boardId, tempItem.id, currentAccessEpoch()),
        createdAt,
        kind: 'checklist.item.create',
        payload: {
          cardId,
          checklistId,
          input: { title, position: tempItem.position },
          tempItem,
        },
      });
    },
    updateChecklistItem: async (cardId, checklistId, itemId, input) => enqueue({
      ...operationBase(boardId, itemId, currentAccessEpoch()),
      kind: 'checklist.item.update',
      payload: { cardId, checklistId, input },
    }),
    deleteChecklistItem: async (cardId, checklistId, itemId) => enqueue({
      ...operationBase(boardId, itemId, currentAccessEpoch()),
      kind: 'checklist.item.delete',
      payload: { cardId, checklistId },
    }),
    toggleChecklistItem: async (cardId, checklistId, itemId, isDone) => enqueue({
      ...operationBase(boardId, itemId, currentAccessEpoch()),
      kind: 'checklist.item.update',
      payload: {
        cardId,
        checklistId,
        input: { isDone },
      },
    }),
    cardOperationState: (cardId) => {
      const related = operations.filter((operation) =>
        operationAffectsCard(operation, cardId));
      if (related.some((operation) => operation.status === 'failed')) return 'failed';
      if (related.some(hasPendingPublication)) return 'pending';
      return null;
    },
  }), [
    applyState,
    boardId,
    canEdit,
    currentAccessEpoch,
    enqueue,
    failedCount,
    flushing,
    hydrated,
    isOnline,
    lastError,
    locallyHidden,
    operations,
    pendingCount,
    relayPendingCount,
    relayCount,
    refresh,
    refreshing,
    retryFailed,
    runSerialized,
    snapshot,
    syncMode,
  ]);
}
