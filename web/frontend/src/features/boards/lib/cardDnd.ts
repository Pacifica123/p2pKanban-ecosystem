import type { Card } from '@/shared/types/api';

const POSITION_STEP = 1024;

export interface CardMoveIntent {
  cardId: string;
  sourceColumnId: string;
  sourceIndex: number;
  targetColumnId: string;
  targetIndex: number;
}

export function sortCardsByPosition(cards: Card[]): Card[] {
  return [...cards].sort((left, right) => {
    if (left.columnId === right.columnId) {
      return left.position - right.position;
    }
    return left.createdAt.localeCompare(right.createdAt);
  });
}

export function groupCardsByColumn(cards: Card[]): Map<string, Card[]> {
  const map = new Map<string, Card[]>();
  for (const card of sortCardsByPosition(cards)) {
    const items = map.get(card.columnId) || [];
    items.push(card);
    map.set(card.columnId, items);
  }
  return map;
}

export function reorderBoardPreview(cards: Card[], intent: CardMoveIntent): Card[] {
  const grouped = groupCardsByColumn(cards);
  const sourceCards = [...(grouped.get(intent.sourceColumnId) || [])];
  const targetCards = intent.sourceColumnId === intent.targetColumnId
    ? sourceCards
    : [...(grouped.get(intent.targetColumnId) || [])];

  const sourceIndex = sourceCards.findIndex((card) => card.id === intent.cardId);
  if (sourceIndex === -1) {
    return sortCardsByPosition(cards);
  }

  const [movedCard] = sourceCards.splice(sourceIndex, 1);
  const safeTargetIndex = clamp(intent.targetIndex, 0, targetCards.length);

  if (intent.sourceColumnId === intent.targetColumnId) {
    sourceCards.splice(safeTargetIndex, 0, { ...movedCard, columnId: intent.targetColumnId });
    grouped.set(intent.sourceColumnId, applySequentialPositions(sourceCards));
  } else {
    targetCards.splice(safeTargetIndex, 0, { ...movedCard, columnId: intent.targetColumnId });
    grouped.set(intent.sourceColumnId, applySequentialPositions(sourceCards));
    grouped.set(intent.targetColumnId, applySequentialPositions(targetCards));
  }

  const updatedById = new Map<string, Card>();
  for (const items of grouped.values()) {
    for (const item of items) {
      updatedById.set(item.id, item);
    }
  }

  return cards.map((card) => updatedById.get(card.id) || card);
}

export function getDropPositionValue(cards: Card[], targetIndex: number): number {
  if (!cards.length) return POSITION_STEP;

  const safeTargetIndex = clamp(targetIndex, 0, cards.length);

  if (safeTargetIndex <= 0) {
    const first = cards[0];
    return first.position > 1 ? first.position / 2 : 0.5;
  }

  if (safeTargetIndex >= cards.length) {
    return cards[cards.length - 1].position + POSITION_STEP;
  }

  const previous = cards[safeTargetIndex - 1];
  const next = cards[safeTargetIndex];
  if (next.position > previous.position) {
    return previous.position + (next.position - previous.position) / 2;
  }

  return previous.position + 0.5;
}

export function buildColumnReorderItems(cards: Card[]): Array<{ cardId: string; position: number }> {
  return applySequentialPositions(cards).map((card) => ({
    cardId: card.id,
    position: card.position,
  }));
}

function applySequentialPositions(cards: Card[]): Card[] {
  return cards.map((card, index) => ({
    ...card,
    position: (index + 1) * POSITION_STEP,
  }));
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
