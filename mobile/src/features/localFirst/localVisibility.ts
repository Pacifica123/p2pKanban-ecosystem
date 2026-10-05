import type { Card, Checklist } from '../../shared/types/api';
import { readSessionJson, writeSessionJson } from '../../shared/storage/storage';
import type { LocalBoardSnapshot } from './model';

interface LocallyHiddenCard {
  card: Card;
  checklists: Checklist[];
  hiddenAt: string;
}

function storageSuffix(boardId: string) {
  return `local-first/hidden-cards/${boardId}`;
}

export async function loadLocallyHiddenCards(boardId: string) {
  const values = await readSessionJson<LocallyHiddenCard[]>(storageSuffix(boardId), []);
  return values.filter((value) => value.card?.id && value.card.boardId === boardId);
}

async function saveLocallyHiddenCards(boardId: string, values: LocallyHiddenCard[]) {
  await writeSessionJson(storageSuffix(boardId), values);
}

export function applyLocalCardVisibility(
  snapshot: LocalBoardSnapshot,
  values: LocallyHiddenCard[],
) {
  const hiddenIds = new Set(values.map((value) => value.card.id));
  if (!hiddenIds.size) return snapshot;
  const checklistsByCardId = Object.fromEntries(
    Object.entries(snapshot.checklistsByCardId)
      .filter(([cardId]) => !hiddenIds.has(cardId)),
  );
  return {
    ...snapshot,
    cards: snapshot.cards.filter((card) => !hiddenIds.has(card.id)),
    checklistsByCardId,
  };
}

export async function hideCardOnThisDevice(
  boardId: string,
  snapshot: LocalBoardSnapshot,
  cardId: string,
) {
  const card = snapshot.cards.find((candidate) => candidate.id === cardId);
  if (!card) throw new Error('Карточка не найдена на устройстве.');
  const current = await loadLocallyHiddenCards(boardId);
  const next = [
    ...current.filter((value) => value.card.id !== cardId),
    {
      card,
      checklists: snapshot.checklistsByCardId[cardId] || [],
      hiddenAt: new Date().toISOString(),
    },
  ];
  await saveLocallyHiddenCards(boardId, next);
  return { snapshot: applyLocalCardVisibility(snapshot, next), hidden: next };
}

export async function restoreCardOnThisDevice(
  boardId: string,
  snapshot: LocalBoardSnapshot,
  cardId: string,
) {
  const current = await loadLocallyHiddenCards(boardId);
  const restored = current.find((value) => value.card.id === cardId);
  const next = current.filter((value) => value.card.id !== cardId);
  await saveLocallyHiddenCards(boardId, next);
  if (!restored || snapshot.cards.some((card) => card.id === cardId)) {
    return { snapshot, hidden: next };
  }
  return {
    snapshot: {
      ...snapshot,
      cards: [...snapshot.cards, restored.card],
      checklistsByCardId: {
        ...snapshot.checklistsByCardId,
        [cardId]: restored.checklists,
      },
      cachedAt: new Date().toISOString(),
    },
    hidden: next,
  };
}

export async function pruneLocallyHiddenCards(boardId: string, deletedIds: string[]) {
  if (!deletedIds.length) return loadLocallyHiddenCards(boardId);
  const deleted = new Set(deletedIds);
  const current = await loadLocallyHiddenCards(boardId);
  const next = current.filter((value) => !deleted.has(value.card.id));
  if (next.length !== current.length) await saveLocallyHiddenCards(boardId, next);
  return next;
}

export async function reconcileHiddenCardsWithCoordinator(
  boardId: string,
  coordinatorCardIds: string[],
) {
  const available = new Set(coordinatorCardIds);
  const current = await loadLocallyHiddenCards(boardId);
  const next = current.filter((value) => available.has(value.card.id));
  if (next.length !== current.length) await saveLocallyHiddenCards(boardId, next);
  return next;
}

export type { LocallyHiddenCard };
