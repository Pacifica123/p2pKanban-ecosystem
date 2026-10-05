import { useCallback, useEffect, useRef, useState, type PropsWithChildren } from 'react';
import { Link } from 'react-router-dom';
import {
  REMINDERS_CHANGED_EVENT,
  REMINDERS_STORAGE_KEY,
  parseLocalDateTime,
  readLocalReminders,
  removeLocalCardReminder,
  type LocalCardReminder,
} from '@/features/reminders/lib/localReminders';
import { Button } from '@/shared/ui/Button';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';

const MAX_TIMEOUT_MS = 2_147_000_000;

function cardUrl(reminder: LocalCardReminder) {
  return `/workspaces/${encodeURIComponent(reminder.workspaceId)}`
    + `/boards/${encodeURIComponent(reminder.boardId)}`
    + `?card=${encodeURIComponent(reminder.cardId)}`;
}

function showSystemNotification(reminder: LocalCardReminder) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  const notification = new Notification('Напоминание о карточке', {
    body: reminder.cardTitle,
    tag: `p2pkanban-card-${reminder.cardId}`,
  });
  notification.onclick = () => {
    window.focus();
    window.location.assign(cardUrl(reminder));
    notification.close();
  };
}

export function LocalReminderProvider({ children }: PropsWithChildren) {
  const { user } = useAuthSession();
  const [fired, setFired] = useState<LocalCardReminder | null>(null);
  const timeoutRef = useRef<number | null>(null);

  const scheduleNext = useCallback(() => {
    if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
    if (!user) {
      timeoutRef.current = null;
      return;
    }
    const now = Date.now();
    const reminders = readLocalReminders(user.id)
      .map((reminder) => ({ reminder, at: parseLocalDateTime(reminder.localDateTime)?.getTime() }))
      .filter((entry): entry is { reminder: LocalCardReminder; at: number } => Boolean(entry.at))
      .sort((left, right) => left.at - right.at);
    const due = reminders.find((entry) => entry.at <= now);
    if (due) {
      removeLocalCardReminder(due.reminder.cardId, user.id);
      setFired(due.reminder);
      showSystemNotification(due.reminder);
      window.setTimeout(scheduleNext, 0);
      return;
    }
    const next = reminders[0];
    if (!next) {
      timeoutRef.current = null;
      return;
    }
    timeoutRef.current = window.setTimeout(
      scheduleNext,
      Math.min(Math.max(next.at - now, 250), MAX_TIMEOUT_MS),
    );
  }, [user]);

  useEffect(() => {
    scheduleNext();
    const changed = () => scheduleNext();
    const storage = (event: StorageEvent) => {
      if (event.key === REMINDERS_STORAGE_KEY) scheduleNext();
    };
    const visible = () => {
      if (document.visibilityState === 'visible') scheduleNext();
    };
    window.addEventListener(REMINDERS_CHANGED_EVENT, changed);
    window.addEventListener('storage', storage);
    document.addEventListener('visibilitychange', visible);
    return () => {
      if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
      window.removeEventListener(REMINDERS_CHANGED_EVENT, changed);
      window.removeEventListener('storage', storage);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [scheduleNext]);

  return (
    <>
      {children}
      {fired ? (
        <aside className="local-reminder-toast" role="status" aria-live="polite">
          <div>
            <strong>Напоминание</strong>
            <p>{fired.cardTitle}</p>
          </div>
          <div className="inline-actions">
            <Link className="button button--primary" to={cardUrl(fired)} onClick={() => setFired(null)}>
              Открыть
            </Link>
            <Button iconOnly variant="ghost" onClick={() => setFired(null)} title="Закрыть" aria-label="Закрыть">×</Button>
          </div>
        </aside>
      ) : null}
    </>
  );
}
