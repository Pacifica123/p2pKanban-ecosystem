import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import type { LocalCardReminder } from './model';
import { parseFloatingLocalDateTime } from './model';
import {
  loadCardReminder,
  loadCardReminders,
  removeStoredCardReminder,
  saveCardReminder,
} from './storage';

export const REMINDER_CHANNEL_ID = 'card-reminders';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

async function ensureReminderChannel() {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync(REMINDER_CHANNEL_ID, {
    name: 'Напоминания о карточках',
    description: 'Локальные напоминания, созданные на этом устройстве',
    importance: Notifications.AndroidImportance.DEFAULT,
    sound: null,
  });
}

async function canNotify(request: boolean) {
  await ensureReminderChannel();
  let permissions = await Notifications.getPermissionsAsync();
  if (!permissions.granted && request) {
    permissions = await Notifications.requestPermissionsAsync();
  }
  return permissions.granted;
}

async function scheduleNative(
  input: Omit<LocalCardReminder, 'notificationId' | 'scheduledForEpochMs' | 'timezoneOffset'>,
  date: Date,
) {
  return Notifications.scheduleNotificationAsync({
    content: {
      title: input.cardTitle,
      body: `Доска: ${input.boardName}`,
      sound: false,
      data: {
        kind: 'card-reminder',
        cardId: input.cardId,
        boardId: input.boardId,
        boardName: input.boardName,
        workspaceId: input.workspaceId,
      },
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DATE,
      date,
      channelId: REMINDER_CHANNEL_ID,
    },
  });
}

export async function scheduleCardReminder(input: {
  cardId: string;
  boardId: string;
  boardName: string;
  workspaceId: string;
  cardTitle: string;
  localDateTime: string;
}) {
  const date = parseFloatingLocalDateTime(input.localDateTime);
  if (!date) throw new Error('Проверьте дату и время напоминания.');
  if (date.getTime() <= Date.now()) {
    throw new Error('Напоминание должно быть запланировано на будущее.');
  }
  if (!await canNotify(true)) {
    throw new Error('Разрешите уведомления для p2pKanban в настройках Android.');
  }

  const previous = await loadCardReminder(input.cardId);
  const notificationId = await scheduleNative({
    ...input,
    createdAt: previous?.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }, date);
  if (previous) {
    await Notifications.cancelScheduledNotificationAsync(previous.notificationId).catch(() => null);
  }
  const timestamp = new Date().toISOString();
  const reminder: LocalCardReminder = {
    ...input,
    notificationId,
    scheduledForEpochMs: date.getTime(),
    timezoneOffset: date.getTimezoneOffset(),
    createdAt: previous?.createdAt || timestamp,
    updatedAt: timestamp,
  };
  await saveCardReminder(reminder);
  return reminder;
}

export async function cancelCardReminder(cardId: string) {
  const reminder = await loadCardReminder(cardId);
  if (reminder) {
    await Notifications.cancelScheduledNotificationAsync(reminder.notificationId).catch(() => null);
  }
  await removeStoredCardReminder(cardId);
}

export async function updateCardReminderTitle(cardId: string, cardTitle: string) {
  const reminder = await loadCardReminder(cardId);
  if (!reminder || reminder.cardTitle === cardTitle) return;
  await scheduleCardReminder({ ...reminder, cardTitle });
}

export async function moveCardReminder(cardId: string, nextCardId: string, cardTitle: string) {
  const reminder = await loadCardReminder(cardId);
  if (!reminder) return;
  const date = parseFloatingLocalDateTime(reminder.localDateTime);
  if (!date || date.getTime() <= Date.now()) {
    await cancelCardReminder(cardId);
    return;
  }
  try {
    await scheduleCardReminder({ ...reminder, cardId: nextCardId, cardTitle });
    await cancelCardReminder(cardId);
  } catch {
    // A notification permission/configuration failure must never replay card.create.
    // Dropping the stale reminder is safer than keeping a deep link to a temporary ID.
    await cancelCardReminder(cardId).catch(() => null);
  }
}

export async function reconcileCardReminders() {
  const reminders = await loadCardReminders();
  const allowed = await canNotify(false);
  for (const reminder of reminders) {
    const date = parseFloatingLocalDateTime(reminder.localDateTime);
    if (!date || date.getTime() <= Date.now()) {
      await cancelCardReminder(reminder.cardId);
      continue;
    }
    const timezoneChanged = reminder.timezoneOffset !== date.getTimezoneOffset();
    const instantChanged = reminder.scheduledForEpochMs !== date.getTime();
    if (!allowed || (!timezoneChanged && !instantChanged)) continue;
    const notificationId = await scheduleNative(reminder, date);
    await Notifications.cancelScheduledNotificationAsync(reminder.notificationId).catch(() => null);
    await saveCardReminder({
      ...reminder,
      notificationId,
      scheduledForEpochMs: date.getTime(),
      timezoneOffset: date.getTimezoneOffset(),
      updatedAt: new Date().toISOString(),
    });
  }
}

export async function cancelAllCardReminders() {
  const reminders = await loadCardReminders();
  await Promise.all(reminders.map((reminder) => (
    Notifications.cancelScheduledNotificationAsync(reminder.notificationId).catch(() => null)
  )));
}
