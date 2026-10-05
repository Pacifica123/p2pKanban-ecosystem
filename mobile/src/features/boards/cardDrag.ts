import type { Card } from '../../shared/types/api';

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

export function getDropColumnIndex(input: {
  scrollOffset: number;
  pointerX: number;
  contentInset: number;
  columnWidth: number;
  gap: number;
  columnCount: number;
}) {
  if (input.columnCount <= 0) return -1;
  const stride = input.columnWidth + input.gap;
  const contentX = input.scrollOffset + input.pointerX - input.contentInset;
  return clamp(Math.floor(Math.max(contentX, 0) / stride), 0, input.columnCount - 1);
}

export function getEdgeScrollOffset(input: {
  scrollOffset: number;
  pointerX: number;
  viewportWidth: number;
  columnWidth: number;
  gap: number;
  columnCount: number;
  threshold?: number;
}) {
  const stride = input.columnWidth + input.gap;
  const currentIndex = clamp(
    Math.round(input.scrollOffset / stride),
    0,
    Math.max(input.columnCount - 1, 0),
  );
  const threshold = input.threshold ?? 54;
  if (input.pointerX <= threshold && currentIndex > 0) {
    return (currentIndex - 1) * stride;
  }
  if (
    input.pointerX >= input.viewportWidth - threshold
    && currentIndex < input.columnCount - 1
  ) {
    return (currentIndex + 1) * stride;
  }
  return null;
}

export function getAppendPosition(
  cards: Card[],
  targetColumnId: string,
  draggedCardId: string,
) {
  return cards
    .filter((card) => (
      card.id !== draggedCardId
      && card.columnId === targetColumnId
      && !card.isArchived
    ))
    .reduce((highest, card) => Math.max(highest, card.position), 0) + 1000;
}

export function moveCardPreview(
  cards: Card[],
  cardId: string,
  targetColumnId: string,
) {
  const position = getAppendPosition(cards, targetColumnId, cardId);
  return cards.map((card) => card.id === cardId
    ? { ...card, columnId: targetColumnId, position }
    : card);
}

export function getAdjacentPosition(cards:Card[],cardId:string,direction:-1|1):number|null {
 const card=cards.find(c=>c.id===cardId);if(!card)return null;
 const ordered=cards.filter(c=>c.columnId===card.columnId&&!c.isArchived).sort((a,b)=>a.position-b.position||a.id.localeCompare(b.id));
 const from=ordered.findIndex(c=>c.id===cardId),to=from+direction;if(from<0||to<0||to>=ordered.length)return null;
 const remaining=ordered.filter(c=>c.id!==cardId),before=remaining[to-1]?.position,after=remaining[to]?.position;
 if(before===undefined)return (after??0)-1024;if(after===undefined)return before+1024;
 const position=(before+after)/2;if(position<=before||position>=after)throw new Error('Позиции совпали: переставьте соседнюю карточку или выполните reorder на web.');return position;
}
