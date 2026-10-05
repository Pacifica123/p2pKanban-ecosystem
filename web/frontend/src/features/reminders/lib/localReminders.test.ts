import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getLocalCardReminder,
  moveLocalCardReminder,
  parseLocalDateTime,
  removeLocalCardReminder,
  saveLocalCardReminder,
  toLocalDateTimeInput,
  updateLocalCardReminderTitle,
} from '@/features/reminders/lib/localReminders';

describe('local card reminders', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it('round-trips a floating local date-time without a timezone suffix', () => {
    const date = new Date(2032, 4, 6, 7, 8);
    const value = toLocalDateTimeInput(date);
    expect(value).toBe('2032-05-06T07:08');
    expect(parseLocalDateTime(value)?.getTime()).toBe(date.getTime());
    expect(parseLocalDateTime('2032-02-31T07:08')).toBeNull();
  });

  it('keeps at most one reminder per card and updates its title', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2032, 0, 1, 10, 0));
    saveLocalCardReminder({
      userId: 'user-1',
      cardId: 'card-1',
      boardId: 'board-1',
      workspaceId: 'workspace-1',
      cardTitle: 'Старая карточка',
      localDateTime: '2032-01-01T11:00',
    });
    saveLocalCardReminder({
      userId: 'user-1',
      cardId: 'card-1',
      boardId: 'board-1',
      workspaceId: 'workspace-1',
      cardTitle: 'Новая карточка',
      localDateTime: '2032-01-01T12:00',
    });
    updateLocalCardReminderTitle('card-1', 'Переименована', 'user-1');
    moveLocalCardReminder('card-1', 'card-2', 'user-1');
    expect(getLocalCardReminder('card-1', 'user-1')).toBeNull();
    expect(getLocalCardReminder('card-2', 'user-1')).toMatchObject({
      cardTitle: 'Переименована',
      localDateTime: '2032-01-01T12:00',
    });
    removeLocalCardReminder('card-2', 'user-1');
    expect(getLocalCardReminder('card-2', 'user-1')).toBeNull();
  });

  it('isolates reminders for the same card between signed-in users', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2032, 0, 1, 10, 0));
    for (const userId of ['user-1', 'user-2']) {
      saveLocalCardReminder({
        userId,
        cardId: 'shared-card-id',
        boardId: 'board-1',
        workspaceId: 'workspace-1',
        cardTitle: `Карточка ${userId}`,
        localDateTime: '2032-01-01T11:00',
      });
    }

    expect(getLocalCardReminder('shared-card-id', 'user-1')?.cardTitle).toBe('Карточка user-1');
    expect(getLocalCardReminder('shared-card-id', 'user-2')?.cardTitle).toBe('Карточка user-2');
    removeLocalCardReminder('shared-card-id', 'user-1');
    expect(getLocalCardReminder('shared-card-id', 'user-1')).toBeNull();
    expect(getLocalCardReminder('shared-card-id', 'user-2')).not.toBeNull();
  });
});
