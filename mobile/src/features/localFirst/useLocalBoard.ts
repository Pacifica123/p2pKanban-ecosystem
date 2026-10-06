import * as Crypto from 'expo-crypto';
import {useAuth} from '../auth/AuthProvider';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import { ApiError, isNetworkError } from '../../shared/api/client';
import { isSyncCanceled, throwIfCanceled, yieldToUi } from '../../shared/lib/uiBudget';
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

/** A full relay pull also collects work that offline peers published late. */
const FULL_PULL_INTERVAL_MS = 10 * 60_000;
const SYNC_INTERVAL_MS = 15_000;
const MAX_RETRY_DELAY_MS = 5 * 60_000;

function pendingKey(operations: LocalOperation[]) {
  return operations.filter(hasPendingPublication).map((operation) => operation.id).join('|');
}

export interface LocalBoardOptions {
  /** False while the screen is covered or the app is in background: no periodic sync. */
  active?: boolean;
}

export function useLocalBoard(
  boardId: string,
  workspaceId: string,
  accessEpoch = 1,
  canEdit = true,
  options: LocalBoardOptions = {},
): LocalBoardRuntime {
  const screenActive = options.active ?? true;
  const { isOnline, networkType } = useNetwork();
  const {user} = useAuth();
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
  const lastFullPullRef = useRef(0);
  const failuresRef = useRef(0);
  const retryAtRef = useRef(0);
  // One controller per opened board: leaving the screen stops its sync between steps.
  const lifecycleRef = useRef<AbortController>(new AbortController());
  const isOnlineRef = useRef(isOnline);
  isOnlineRef.current = isOnline;

  const currentAccessEpoch = useCallback(() => Math.max(
    accessEpoch,
    roamingCapabilityRef.current?.capabilityEpoch || 1,
  ), [accessEpoch]);

  const runSerialized = useCallback(serializeLocalState, []);

  const applyState = useCallback((
    nextSnapshot: LocalBoardSnapshot | null,
    nextOperations: LocalOperation[],
  ) => {
    if (lifecycleRef.current.signal.aborted) return;
    snapshotRef.current = nextSnapshot;
    operationsRef.current = nextOperations;
    setSnapshot(nextSnapshot);
    setOperations(nextOperations.filter((operation) => operation.boardId === boardId));
  }, [boardId]);

  const noteResult = useCallback((error: unknown) => {
    if (isSyncCanceled(error) || lifecycleRef.current.signal.aborted) return;
    if (error) {
      failuresRef.current += 1;
      retryAtRef.current = Date.now()
        + Math.min(SYNC_INTERVAL_MS * 2 ** (failuresRef.current - 1), MAX_RETRY_DELAY_MS);
      setLastError(message(error));
    } else {
      failuresRef.current = 0;
      retryAtRef.current = 0;
    }
  }, []);

  const refresh = useCallback(async (request: { full?: boolean } = {}) => {
    if (!isOnlineRef.current || refreshLock.current) return;
    const signal = lifecycleRef.current.signal;
    refreshLock.current = true;
    setRefreshing(true);
    setLastError(null);
    let failure: unknown = null;
    try {
      const installed = roamingCapabilityRef.current || await loadRoamingCapability(boardId);
      if (installed) {
        roamingCapabilityRef.current = installed;
        const mode = request.full || Date.now() - lastFullPullRef.current >= FULL_PULL_INTERVAL_MS
          ? 'full' as const
          : 'incremental' as const;
        const relay = await pullRoamingBoard(installed, snapshotRef.current, {
          signal, mode, materialize: 'if-changed',
        });
        if (mode === 'full') lastFullPullRef.current = Date.now();
        throwIfCanceled(signal);
        if (relay.changed) {
          await runSerialized(async () => {
            throwIfCanceled(signal);
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
        }
        setSyncMode('roaming'); setRelayCount(relay.relayCount);
        return;
      }

      // Initial enrollment through the HTTP node. Network never runs under the
      // local storage lock: a slow node must not delay a tap on the board.
      await touchWorkspaceSync(workspaceId).catch(() => null);
      const capabilityPromise = getRoamingAuthorPublicKey()
        .then((authorPublicKey) => provisionRoamingBoard(boardId, authorPublicKey))
        .catch(() => null);
      let coordinatorSnapshot: LocalBoardSnapshot;
      let provisionedCapability: RoamingCapability | null;
      try {
        [coordinatorSnapshot, provisionedCapability] = await Promise.all([
          fetchBoardSnapshot(boardId, workspaceId),
          capabilityPromise,
        ]);
      } catch (error) {
        if (coordinatorUnavailable(error)) {
          nodeUnavailableUntilRef.current = Date.now() + 30_000;
        }
        throw error;
      }
      throwIfCanceled(signal);
      const merged = await runSerialized(async () => {
        if (provisionedCapability) {
          const previousCapability = roamingCapabilityRef.current;
          const rotated = Boolean(previousCapability && (
            previousCapability.capabilityEpoch !== provisionedCapability.capabilityEpoch
            || previousCapability.boardTag !== provisionedCapability.boardTag
          ));
          if (rotated) await resetRoamingApplyState(boardId);
          await installRoamingCapability(provisionedCapability);
          roamingCapabilityRef.current = provisionedCapability;
          setSyncMode('roaming');
          setRelayCount(provisionedCapability.relays.length);
        }
        const allOperations = await loadOperationQueue();
        const nextHidden = await reconcileHiddenCardsWithCoordinator(
          boardId,
          coordinatorSnapshot.cards.map((card) => card.id),
        );
        setLocallyHidden(nextHidden);
        const seeded = applyLocalCardVisibility(coordinatorSnapshot, nextHidden);
        nodeUnavailableUntilRef.current = 0;
        const result = await persistServerSnapshot(mergeBoardSnapshots(seeded, null), allOperations);
        applyState(result, allOperations);
        return result;
      });
      if (provisionedCapability?.canWrite) {
        // A first publication of the baseline; the relay is not awaited by the UI.
        void publishBoardSnapshot(provisionedCapability, merged).catch(() => undefined);
      }
    } catch (error) {
      failure = error;
    } finally {
      refreshLock.current = false;
      setRefreshing(false);
      noteResult(failure);
    }
  }, [applyState, boardId, noteResult, runSerialized, workspaceId]);

  /** HTTP coordinator path for boards without a key yet. One operation per step. */
  const flushThroughNode = useCallback(async (signal: AbortSignal) => {
    for (;;) {
      throwIfCanceled(signal);
      const next = await runSerialized(async () => {
        let allOperations = await loadOperationQueue();
        const currentSnapshot = snapshotRef.current;
        if (!currentSnapshot) return null;
        const candidates = allOperations
          .filter((operation) => operation.boardId === boardId && hasPendingPublication(operation))
          .sort((left, right) => left.createdAt.localeCompare(right.createdAt));
        for (const current of candidates) {
          const activeEpoch = currentAccessEpoch();
          if ((current.accessEpoch || 1) === activeEpoch) return current;
          const errorText = 'Отложенное изменение относится к отозванному поколению доступа и не будет применено.';
          allOperations = allOperations.map((candidate) => candidate.id === current.id
            ? { ...candidate, status: 'failed', attempts: candidate.attempts + 1, lastError: errorText }
            : candidate);
          await persistBoardAndQueue(currentSnapshot, allOperations);
          applyState(currentSnapshot, allOperations);
          setLastError(errorText);
        }
        return null;
      });
      if (!next) return;
      const capability = roamingCapabilityRef.current || await loadRoamingCapability(boardId);
      if (capability) {
        roamingCapabilityRef.current = capability;
        return; // Enrollment raced this REST pass; next flush uses the journal.
      }
      if (next.status === 'relay_pending') {
        setLastError('Для восстановления старой очереди нужен сохранённый ключ доски.');
        return;
      }

      // The request runs outside the lock; its result is applied to the latest state.
      type Applied = (snapshot: LocalBoardSnapshot, operations: LocalOperation[]) => {
        snapshot: LocalBoardSnapshot; operations: LocalOperation[];
      };
      let applyRemote: Applied;
      try {
        if (next.kind === 'board.appearance.update') {
          const saved = await updateBoardAppearanceRemote(boardId, next.payload.input);
          applyRemote = (snapshot, operations) => ({
            snapshot: { ...snapshot, appearance: saved, cachedAt: saved.updatedAt || now() },
            operations,
          });
        } else if (next.kind === 'card.create') {
          const created = await createCardRemote(boardId, next.payload.input);
          await moveCardReminder(next.entityId, created.id, created.title);
          applyRemote = (snapshot, operations) => replaceCreatedCard(snapshot, operations, next.entityId, created);
        } else if (next.kind === 'card.update') {
          const updated = await updateCardRemote(next.entityId, next.payload.input);
          applyRemote = (snapshot, operations) => ({ snapshot: replaceCardInSnapshot(snapshot, updated), operations });
        } else if (next.kind === 'card.move') {
          const moved = await moveCardRemote(next.entityId, next.payload.input);
          applyRemote = (snapshot, operations) => ({ snapshot: replaceCardInSnapshot(snapshot, moved), operations });
        } else if (next.kind === 'card.archive') {
          const archived = await archiveCardRemote(next.entityId);
          applyRemote = (snapshot, operations) => ({ snapshot: replaceCardInSnapshot(snapshot, archived), operations });
        } else if (next.kind === 'card.unarchive') {
          const restored = await unarchiveCardRemote(next.entityId);
          applyRemote = (snapshot, operations) => ({ snapshot: replaceCardInSnapshot(snapshot, restored), operations });
        } else if (next.kind === 'card.delete') {
          await deleteCardRemote(next.entityId);
          applyRemote = (snapshot, operations) => ({ snapshot: removeCardFromSnapshot(snapshot, next.entityId), operations });
        } else if (next.kind === 'checklist.create') {
          const created = await createChecklistRemote(next.payload.cardId, next.payload.input);
          applyRemote = (snapshot, operations) => replaceCreatedChecklist(
            snapshot, operations, next.payload.cardId, next.entityId, created);
        } else if (next.kind === 'checklist.update') {
          const updated = await updateChecklistRemote(next.entityId, next.payload.input);
          applyRemote = (snapshot, operations) => ({
            snapshot: replaceChecklist(snapshot, next.payload.cardId, updated), operations,
          });
        } else if (next.kind === 'checklist.delete') {
          await deleteChecklistRemote(next.entityId);
          applyRemote = (snapshot, operations) => ({ snapshot, operations });
        } else if (next.kind === 'checklist.item.create') {
          const created = await createChecklistItemRemote(next.payload.checklistId, next.payload.input);
          applyRemote = (snapshot, operations) => replaceCreatedChecklistItem(
            snapshot, operations, next.payload.cardId, next.entityId, created);
        } else if (next.kind === 'checklist.item.update') {
          const updated = await updateChecklistItemRemote(next.entityId, next.payload.input);
          applyRemote = (snapshot, operations) => ({
            snapshot: replaceChecklistItem(snapshot, next.payload.cardId, updated), operations,
          });
        } else {
          await deleteChecklistItemRemote(next.entityId);
          applyRemote = (snapshot, operations) => ({ snapshot, operations });
        }
      } catch (error) {
        if (coordinatorUnavailable(error)) {
          nodeUnavailableUntilRef.current = Date.now() + 30_000;
          throw new Error('Узел недоступен; для relay требуется первоначальная подготовка доски.');
        }
        const errorText = error instanceof ApiError && error.status === 403
          ? 'Изменение больше не разрешено. Проверьте доступ к пространству.'
          : message(error);
        await runSerialized(async () => {
          const currentSnapshot = snapshotRef.current;
          if (!currentSnapshot) return;
          const allOperations = (await loadOperationQueue()).map((candidate) => candidate.id === next.id
            ? { ...candidate, status: 'failed' as const, attempts: candidate.attempts + 1, lastError: errorText }
            : candidate);
          await persistBoardAndQueue(currentSnapshot, allOperations);
          applyState(currentSnapshot, allOperations);
        });
        setLastError(errorText);
        continue;
      }

      nodeUnavailableUntilRef.current = 0;
      await runSerialized(async () => {
        const currentSnapshot = snapshotRef.current;
        if (!currentSnapshot) return;
        const applied = applyRemote(currentSnapshot, await loadOperationQueue());
        const remaining = applied.operations.filter((candidate) => candidate.id !== next.id);
        const nextSnapshot = applyOperations(
          applied.snapshot,
          remaining.filter((operation) => operation.boardId === boardId),
        );
        await persistBoardAndQueue(nextSnapshot, remaining);
        applyState(nextSnapshot, remaining);
      });
    }
  }, [applyState, boardId, currentAccessEpoch, runSerialized]);

  const flush = useCallback(async () => {
    if (!isOnlineRef.current || flushLock.current) return;
    const signal = lifecycleRef.current.signal;
    flushLock.current = true;
    setFlushing(true);
    setLastError(null);
    let failure: unknown = null;

    try {
      const installed = roamingCapabilityRef.current || await loadRoamingCapability(boardId);
      if (!installed) {
        await flushThroughNode(signal);
        return;
      }
      roamingCapabilityRef.current = installed;
      // Commit legacy pending intentions locally; transport never holds the UI storage lock.
      await runSerialized(async () => {
        let local = snapshotRef.current;
        if (!local) return;
        let queue = await loadOperationQueue();
        let changed = false;
        for (const initial of queue.filter(op => op.boardId === boardId && op.status !== 'failed')) {
          throwIfCanceled(signal);
          let operation = queue.find(op => op.id === initial.id)!;
          if ((operation.accessEpoch || 1) !== installed.capabilityEpoch) {
            queue = queue.map(op => op.id === operation.id ? {...op, status:'failed',lastError:'Изменилось поколение доступа; требуется обновлённый capability.'} : op);
            changed = true;
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
            local = replacement.snapshot; queue = replacement.operations; changed = true;
            operation = queue.find(op => op.id === initial.id)!;
          }
          if (canPublishThroughRoaming(operation)) await commitLocalOperation(installed, operation, local, local, true);
        }
        if (changed) {
          await persistBoardAndQueue(local, queue);
          applyState(local, queue);
        }
      });
      try { await flushReplicaJournal(installed); }
      catch (error) { failure = error; }
      throwIfCanceled(signal);
      await runSerialized(async () => {
        const local = snapshotRef.current;
        if (!local) return;
        const delivered = await publishedOperationIds(installed);
        const before = await loadOperationQueue();
        const queue = before.filter(op => op.boardId !== boardId || !delivered.has(op.id));
        if (queue.length === before.length) return;
        await persistBoardAndQueue(local, queue);
        applyState(local, queue);
      });
      setSyncMode('roaming'); setRelayCount(installed.relays.length);
    } catch (error) {
      failure = error;
    } finally {
      flushLock.current = false;
      setFlushing(false);
      noteResult(failure);
    }
  }, [applyState, boardId, flushThroughNode, noteResult, runSerialized]);

  const flushRef = useRef(flush);
  flushRef.current = flush;
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  // Opening a board shows the stored copy at once. Journal recovery and the
  // network never stand between the user and the board, and a change of the
  // network type no longer re-opens the board.
  useEffect(() => {
    const lifecycle = new AbortController();
    lifecycleRef.current = lifecycle;
    lastFullPullRef.current = 0;
    failuresRef.current = 0;
    retryAtRef.current = 0;
    setHydrated(false);
    snapshotRef.current = null;
    setSnapshot(null);
    void Promise.all([
      loadLocalBoardState(boardId),
      loadRoamingCapability(boardId),
      loadLocallyHiddenCards(boardId),
    ]).then(async ([local, capability, hidden]) => {
      if (lifecycle.signal.aborted) return;
      setLocallyHidden(hidden);
      roamingCapabilityRef.current = capability;
      if (capability) {
        setSyncMode('roaming');
        setRelayCount(capability.relays.length);
      }
      const stored = local.snapshot ? applyLocalCardVisibility(local.snapshot, hidden) : null;
      applyState(stored, local.operations);
      setHydrated(true);

      if (capability) {
        // A crash between journal commit and snapshot write is repaired after the board is visible.
        await yieldToUi();
        await runSerialized(async () => {
          if (lifecycle.signal.aborted || snapshotRef.current !== stored) return;
          const recovered = await recoverLocalReplica(capability, local.snapshot);
          if (!recovered || lifecycle.signal.aborted || snapshotRef.current !== stored) return;
          applyState(applyLocalCardVisibility(recovered, hidden), operationsRef.current);
        });
      }
      if (!isOnlineRef.current || lifecycle.signal.aborted) return;
      const hasPending = local.operations.some(hasPendingPublication);
      if (hasPending) await flushRef.current();
      if (!lifecycle.signal.aborted) await refreshRef.current({ full: true });
    }).catch((error) => {
      if (lifecycle.signal.aborted) return;
      setLastError(message(error));
      setHydrated(true);
    });
    return () => {
      lifecycle.abort();
    };
  }, [applyState, boardId, runSerialized]);

  // New local work is sent once; a failed attempt waits for the timer and backoff.
  const pending = pendingKey(operations);
  useEffect(() => {
    if (isOnline && hydrated && pending) void flushRef.current();
  }, [hydrated, isOnline, pending]);

  useEffect(() => {
    if (!isOnline || !hydrated || !screenActive) return;
    let foreground = AppState.currentState === 'active';
    let running = false;
    const synchronize = async (full: boolean) => {
      if (!foreground || running || lifecycleRef.current.signal.aborted) return;
      if (!full && Date.now() < retryAtRef.current) return;
      running = true;
      try {
        await flushRef.current();
        await refreshRef.current({ full });
      } finally {
        running = false;
      }
    };
    const timer = setInterval(() => { void synchronize(false); }, SYNC_INTERVAL_MS);
    const subscription = AppState.addEventListener('change', state => {
      foreground = state === 'active';
      if (foreground) void synchronize(true);
    });
    return () => { clearInterval(timer); subscription.remove(); };
  }, [hydrated, isOnline, screenActive, networkType]);

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
    retryAtRef.current = 0;
  }, [applyState, boardId, canEdit, runSerialized, user]);

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
    retryAtRef.current = 0;
    await flush();
  }, [applyState, boardId, flush, runSerialized]);

  const manualRefresh = useCallback(async () => {
    retryAtRef.current = 0;
    await refresh({ full: true });
  }, [refresh]);

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
    refresh: manualRefresh,
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
    manualRefresh,
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
