export const REMINDERS_STORAGE_KEY = 'p2pkanban:card-reminders:v1';
export const REMINDERS_CHANGED_EVENT = 'p2pkanban:card-reminders-changed';

export interface LocalCardReminder {
  userId: string;
  cardId: string;
  boardId: string;
  workspaceId: string;
  cardTitle: string;
  localDateTime: string;
  createdAt: string;
  updatedAt: string;
}

function storageAvailable() {
  return typeof window !== 'undefined' && Boolean(window.localStorage);
}

export function parseLocalDateTime(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const date = new Date(year, month - 1, day, hour, minute, 0, 0);
  if (
    date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
    || date.getHours() !== hour
    || date.getMinutes() !== minute
  ) return null;
  return date;
}

export function toLocalDateTimeInput(date: Date) {
  const part = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${part(date.getMonth() + 1)}-${part(date.getDate())}`
    + `T${part(date.getHours())}:${part(date.getMinutes())}`;
}

export function readLocalReminders(userId?: string): LocalCardReminder[] {
  if (!storageAvailable()) return [];
  try {
    const value = JSON.parse(window.localStorage.getItem(REMINDERS_STORAGE_KEY) || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is LocalCardReminder => Boolean(
      item
      && typeof item === 'object'
      && typeof item.userId === 'string'
      && typeof item.cardId === 'string'
      && typeof item.boardId === 'string'
      && typeof item.workspaceId === 'string'
      && typeof item.cardTitle === 'string'
      && typeof item.localDateTime === 'string'
      && parseLocalDateTime(item.localDateTime),
    )).filter((item) => !userId || item.userId === userId);
  } catch {
    return [];
  }
}

function writeLocalReminders(reminders: LocalCardReminder[]) {
  if (!storageAvailable()) return;
  window.localStorage.setItem(REMINDERS_STORAGE_KEY, JSON.stringify(reminders));
  window.dispatchEvent(new CustomEvent(REMINDERS_CHANGED_EVENT));
}

export function getLocalCardReminder(cardId: string, userId: string) {
  return readLocalReminders(userId).find((item) => item.cardId === cardId) || null;
}

export function saveLocalCardReminder(input: Omit<LocalCardReminder, 'createdAt' | 'updatedAt'>) {
  const scheduledAt = parseLocalDateTime(input.localDateTime);
  if (!scheduledAt) throw new Error('Укажите существующие локальные дату и время.');
  if (scheduledAt.getTime() <= Date.now()) {
    throw new Error('Напоминание должно быть запланировано на будущее.');
  }
  const current = readLocalReminders();
  const previous = current.find((item) => (
    item.userId === input.userId && item.cardId === input.cardId
  ));
  const timestamp = new Date().toISOString();
  const next: LocalCardReminder = {
    ...input,
    createdAt: previous?.createdAt || timestamp,
    updatedAt: timestamp,
  };
  writeLocalReminders([
    ...current.filter((item) => (
      item.userId !== input.userId || item.cardId !== input.cardId
    )),
    next,
  ]);
  return next;
}

export function removeLocalCardReminder(cardId: string, userId: string) {
  const current = readLocalReminders();
  if (!current.some((item) => item.cardId === cardId && item.userId === userId)) return;
  writeLocalReminders(current.filter((item) => (
    item.cardId !== cardId || item.userId !== userId
  )));
}

export function updateLocalCardReminderTitle(cardId: string, cardTitle: string, userId: string) {
  const current = readLocalReminders();
  const reminder = current.find((item) => item.cardId === cardId && item.userId === userId);
  if (!reminder || reminder.cardTitle === cardTitle) return;
  writeLocalReminders(current.map((item) => item.cardId === cardId && item.userId === userId
    ? { ...item, cardTitle, updatedAt: new Date().toISOString() }
    : item));
}

export function moveLocalCardReminder(fromCardId: string, toCardId: string, userId: string) {
  if (fromCardId === toCardId) return;
  const current = readLocalReminders();
  const source = current.find((item) => item.cardId === fromCardId && item.userId === userId);
  if (!source) return;
  writeLocalReminders([
    ...current.filter((item) => (
      item.userId !== userId || (item.cardId !== fromCardId && item.cardId !== toCardId)
    )),
    { ...source, cardId: toCardId, updatedAt: new Date().toISOString() },
  ]);
}

export async function requestBrowserNotificationPermission() {
  if (typeof Notification === 'undefined') return 'unsupported' as const;
  if (Notification.permission !== 'default') return Notification.permission;
  return Notification.requestPermission();
}
