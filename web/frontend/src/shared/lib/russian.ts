type Gender = 'masculine' | 'feminine' | 'neuter' | 'plural';

const entityLabels: Record<string, { label: string; gender: Gender }> = {
  board: { label: 'Доска', gender: 'feminine' },
  card: { label: 'Карточка', gender: 'feminine' },
  checklist: { label: 'Чек-лист', gender: 'masculine' },
  checklist_item: { label: 'Пункт чек-листа', gender: 'masculine' },
  column: { label: 'Колонка', gender: 'feminine' },
  comment: { label: 'Комментарий', gender: 'masculine' },
  label: { label: 'Метка', gender: 'feminine' },
  workspace: { label: 'Пространство', gender: 'neuter' },
  workspace_member: { label: 'Участник пространства', gender: 'masculine' },
};

const actionForms: Record<string, Record<Gender, string>> = {
  archived: { masculine: 'архивирован', feminine: 'архивирована', neuter: 'архивировано', plural: 'архивированы' },
  completed: { masculine: 'завершён', feminine: 'завершена', neuter: 'завершено', plural: 'завершены' },
  created: { masculine: 'создан', feminine: 'создана', neuter: 'создано', plural: 'созданы' },
  deleted: { masculine: 'удалён', feminine: 'удалена', neuter: 'удалено', plural: 'удалены' },
  moved: { masculine: 'перемещён', feminine: 'перемещена', neuter: 'перемещено', plural: 'перемещены' },
  reopened: { masculine: 'открыт снова', feminine: 'открыта снова', neuter: 'открыто снова', plural: 'открыты снова' },
  reordered: { masculine: 'переставлен', feminine: 'переставлена', neuter: 'переставлено', plural: 'переставлены' },
  restored: { masculine: 'восстановлен', feminine: 'восстановлена', neuter: 'восстановлено', plural: 'восстановлены' },
  updated: { masculine: 'изменён', feminine: 'изменена', neuter: 'изменено', plural: 'изменены' },
};

const exactActivityLabels: Record<string, string> = {
  'board.appearance.updated': 'Оформление доски изменено',
  'card.completed': 'Карточка изменена',
  'card.labels.updated': 'Метки карточки изменены',
  'card.reopened': 'Карточка изменена',
};

const fieldLabels: Record<string, string> = {
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
  if (exactActivityLabels[kind]) return exactActivityLabels[kind];
  const [entity, action] = kind.split('.');
  const subject = entityLabels[entity || ''];
  const forms = actionForms[action || ''];
  if (!subject || !forms) return kind.split('.').join(' · ');
  return `${subject.label} ${forms[subject.gender]}`;
}

export function changedFieldsLabel(fieldMask: string[]) {
  return [...new Set(fieldMask)]
    .filter((field) => ![
      '*', '__lifecycle', 'updatedAt', 'status', 'completedAt',
    ].includes(field))
    .map((field) => fieldLabels[field] || field)
    .join(', ');
}
