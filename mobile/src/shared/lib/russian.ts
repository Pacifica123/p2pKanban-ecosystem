type Gender = 'masculine' | 'feminine' | 'neuter';

const entities: Record<string, { label: string; gender: Gender }> = {
  board: { label: 'Доска', gender: 'feminine' },
  card: { label: 'Карточка', gender: 'feminine' },
  checklist: { label: 'Чек-лист', gender: 'masculine' },
  checklist_item: { label: 'Пункт чек-листа', gender: 'masculine' },
  column: { label: 'Колонка', gender: 'feminine' },
  comment: { label: 'Комментарий', gender: 'masculine' },
  label: { label: 'Метка', gender: 'feminine' },
  workspace: { label: 'Пространство', gender: 'neuter' },
};

const actions: Record<string, Record<Gender, string>> = {
  archived: { masculine: 'архивирован', feminine: 'архивирована', neuter: 'архивировано' },
  completed: { masculine: 'завершён', feminine: 'завершена', neuter: 'завершено' },
  created: { masculine: 'создан', feminine: 'создана', neuter: 'создано' },
  deleted: { masculine: 'удалён', feminine: 'удалена', neuter: 'удалено' },
  moved: { masculine: 'перемещён', feminine: 'перемещена', neuter: 'перемещено' },
  reopened: { masculine: 'открыт снова', feminine: 'открыта снова', neuter: 'открыто снова' },
  reordered: { masculine: 'переставлен', feminine: 'переставлена', neuter: 'переставлено' },
  restored: { masculine: 'восстановлен', feminine: 'восстановлена', neuter: 'восстановлено' },
  updated: { masculine: 'изменён', feminine: 'изменена', neuter: 'изменено' },
};

const exactActivities: Record<string, string> = {
  'board.appearance.updated': 'Оформление доски изменено',
  'card.completed': 'Карточка изменена',
  'card.labels.updated': 'Метки карточки изменены',
  'card.reopened': 'Карточка изменена',
};

const fields: Record<string, string> = {
  archivedAt: 'дата архивации',
  body: 'текст комментария',
  cardPreviewMode: 'вид карточек',
  checklists: 'чек-листы',
  columnId: 'колонка',
  columnDensity: 'плотность колонок',
  color: 'цвет',
  colorToken: 'цвет колонки',
  customProperties: 'дополнительные свойства',
  description: 'описание',
  dueAt: 'срок',
  isArchived: 'состояние архива',
  isDone: 'выполнение',
  labelIds: 'метки',
  labels: 'метки',
  name: 'название',
  parentCardId: 'родительская карточка',
  position: 'положение',
  priority: 'приоритет',
  showCardDates: 'показ дат',
  showCardDescription: 'показ описания',
  showChecklistProgress: 'прогресс чек-листа',
  startAt: 'дата начала',
  themePreset: 'тема',
  title: 'название',
  wallpaper: 'фон',
  wipLimit: 'лимит незавершённой работы',
};

export function pluralRu(count: number, one: string, few: string, many: string) {
  const absolute = Math.abs(count) % 100;
  const last = absolute % 10;
  if (absolute >= 11 && absolute <= 14) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

export function formatCountRu(count: number, one: string, few: string, many: string) {
  return `${count} ${pluralRu(count, one, few, many)}`;
}

export function activityLabel(kind: string) {
  if (exactActivities[kind]) return exactActivities[kind];
  const [entity, action] = kind.split('.');
  const subject = entities[entity || ''];
  const forms = actions[action || ''];
  if (!subject || !forms) return kind.split('.').join(' · ');
  return `${subject.label} ${forms[subject.gender]}`;
}

export function changedFieldsLabel(fieldMask: string[]) {
  return [...new Set(fieldMask)]
    .filter((field) => ![
      '*', '__lifecycle', 'updatedAt', 'status', 'completedAt',
    ].includes(field))
    .map((field) => fields[field] || field)
    .join(', ');
}
