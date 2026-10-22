import type { Card, CardPriority } from '@/shared/types/api';

export interface CardFormValues {
  title: string;
  description: string;
  priority: CardPriority;
  columnId: string;
}

export function cardFormValues(card: Pick<Card, 'title' | 'description' | 'priority' | 'columnId'>): CardFormValues {
  return {
    title: card.title,
    description: card.description || '',
    priority: card.priority || null,
    columnId: card.columnId,
  };
}

// Опрос узла пересоздаёт объект карточки, когда на доске меняется любая карточка.
// Поле формы принимает новое значение с узла, только если пользователь его не правил:
// текущее значение совпадает с тем, что форма получила с узла в прошлый раз.
export function mergeCardForm<K extends keyof CardFormValues>(
  field: K,
  current: CardFormValues[K],
  previousSynced: CardFormValues,
  nextSynced: CardFormValues,
): CardFormValues[K] {
  return current === previousSynced[field] ? nextSynced[field] : current;
}
