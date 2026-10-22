import { expect, test } from 'vitest';
import { cardFormValues, mergeCardForm } from '@/features/cards/lib/cardForm';

const synced = cardFormValues({ title: 'Карточка', description: null, priority: null, columnId: 'col-1' });

test('unsaved priority survives a poll that re-creates the card', () => {
  const polled = cardFormValues({ title: 'Карточка', description: null, priority: null, columnId: 'col-1' });
  expect(mergeCardForm('priority', 'urgent', synced, polled)).toBe('urgent');
});

test('untouched field takes the value from another device', () => {
  const polled = cardFormValues({ title: 'С телефона', description: null, priority: 'high', columnId: 'col-1' });
  expect(mergeCardForm('title', 'Карточка', synced, polled)).toBe('С телефона');
  expect(mergeCardForm('priority', null, synced, polled)).toBe('high');
});

test('edited field keeps the user value even if the node changed it', () => {
  const polled = cardFormValues({ title: 'С телефона', description: null, priority: 'low', columnId: 'col-2' });
  expect(mergeCardForm('title', 'Моё', synced, polled)).toBe('Моё');
  expect(mergeCardForm('priority', 'urgent', synced, polled)).toBe('urgent');
  expect(mergeCardForm('columnId', 'col-3', synced, polled)).toBe('col-3');
});
