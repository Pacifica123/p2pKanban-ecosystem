export interface LocalCardReminder {
  cardId: string;
  boardId: string;
  boardName: string;
  workspaceId: string;
  cardTitle: string;
  localDateTime: string;
  notificationId: string;
  scheduledForEpochMs: number;
  timezoneOffset: number;
  createdAt: string;
  updatedAt: string;
}

function pad(value: number) {
  return String(value).padStart(2, '0');
}

export function formatFloatingLocalDateTime(date: Date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function parseFloatingLocalDateTime(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const [, rawYear, rawMonth, rawDay, rawHour, rawMinute] = match;
  const year = Number(rawYear);
  const month = Number(rawMonth);
  const day = Number(rawDay);
  const hour = Number(rawHour);
  const minute = Number(rawMinute);
  if (year < 2000 || year > 2100 || hour > 23 || minute > 59) return null;
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

export function reminderFields(value: string | null | undefined) {
  const parsed = value ? parseFloatingLocalDateTime(value) : null;
  const date = parsed || new Date(Date.now() + 60 * 60_000);
  return {
    date: `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`,
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  };
}

export function reminderFromFields(dateValue: string, timeValue: string) {
  const dateMatch = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(dateValue.trim());
  const timeMatch = /^(\d{2}):(\d{2})$/.exec(timeValue.trim());
  if (!dateMatch || !timeMatch) return null;
  return `${dateMatch[3]}-${dateMatch[2]}-${dateMatch[1]}T${timeMatch[1]}:${timeMatch[2]}`;
}

export function quickReminder(kind: 'hour' | 'tomorrow') {
  const date = new Date();
  date.setSeconds(0, 0);
  if (kind === 'hour') date.setHours(date.getHours() + 1);
  else {
    date.setDate(date.getDate() + 1);
    date.setHours(9, 0, 0, 0);
  }
  return formatFloatingLocalDateTime(date);
}
