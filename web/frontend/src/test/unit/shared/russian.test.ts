import {
  activityLabel,
  changedFieldsLabel,
  formatCountRu,
  pluralRu,
} from '@/shared/lib/russian';

describe('Russian UI grammar', () => {
  it('uses Russian plural forms for edge cases', () => {
    expect(formatCountRu(1, 'карточка', 'карточки', 'карточек')).toBe('1 карточка');
    expect(formatCountRu(2, 'карточка', 'карточки', 'карточек')).toBe('2 карточки');
    expect(formatCountRu(5, 'карточка', 'карточки', 'карточек')).toBe('5 карточек');
    expect(pluralRu(11, 'изменение', 'изменения', 'изменений')).toBe('изменений');
    expect(pluralRu(21, 'изменение', 'изменения', 'изменений')).toBe('изменение');
    expect(pluralRu(24, 'изменение', 'изменения', 'изменений')).toBe('изменения');
  });

  it('agrees activity actions with their subjects', () => {
    expect(activityLabel('card.created')).toBe('Карточка создана');
    expect(activityLabel('checklist.created')).toBe('Чек-лист создан');
    expect(activityLabel('checklist_item.created')).toBe('Пункт чек-листа создан');
    expect(activityLabel('workspace.created')).toBe('Пространство создано');
  });

  it('hides protocol-only fields and translates readable fields', () => {
    expect(changedFieldsLabel(['*', 'columnId', 'updatedAt', 'isDone']))
      .toBe('колонка, выполнение');
  });
});
