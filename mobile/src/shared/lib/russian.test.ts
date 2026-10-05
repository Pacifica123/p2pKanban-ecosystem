import {
  activityLabel,
  changedFieldsLabel,
  formatCountRu,
} from './russian';

describe('Russian UI grammar', () => {
  test.each([
    [1, '1 карточка'],
    [2, '2 карточки'],
    [5, '5 карточек'],
    [11, '11 карточек'],
    [21, '21 карточка'],
    [24, '24 карточки'],
  ])('formats %i with the correct plural form', (count, expected) => {
    expect(formatCountRu(count, 'карточка', 'карточки', 'карточек')).toBe(expected);
  });

  it('agrees activity action with the entity', () => {
    expect(activityLabel('card.created')).toBe('Карточка создана');
    expect(activityLabel('checklist.created')).toBe('Чек-лист создан');
    expect(activityLabel('checklist_item.created')).toBe('Пункт чек-листа создан');
  });

  it('translates fields and removes protocol-only markers', () => {
    expect(changedFieldsLabel(['*', 'columnId', 'updatedAt', 'isDone']))
      .toBe('колонка, выполнение');
  });
});
