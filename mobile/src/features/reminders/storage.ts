import { readSessionJson, writeSessionJson } from '../../shared/storage/storage';
import type { LocalCardReminder } from './model';

const REMINDERS_KEY = 'reminders/cards';

export async function loadCardReminders() {
  const values = await readSessionJson<LocalCardReminder[]>(REMINDERS_KEY, []);
  return values.filter((value) => Boolean(
    value.cardId
    && value.boardId
    && value.workspaceId
    && value.localDateTime
    && value.notificationId,
  ));
}

export async function loadCardReminder(cardId: string) {
  return (await loadCardReminders()).find((value) => value.cardId === cardId) || null;
}

export async function saveCardReminder(reminder: LocalCardReminder) {
  const current = await loadCardReminders();
  const next = current.some((value) => value.cardId === reminder.cardId)
    ? current.map((value) => value.cardId === reminder.cardId ? reminder : value)
    : [...current, reminder];
  await writeSessionJson(REMINDERS_KEY, next);
}

export async function removeStoredCardReminder(cardId: string) {
  const current = await loadCardReminders();
  await writeSessionJson(
    REMINDERS_KEY,
    current.filter((value) => value.cardId !== cardId),
  );
}
