import * as Notifications from 'expo-notifications';
import type { PropsWithChildren } from 'react';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import {
  flushReminderTarget,
  openReminderTarget,
} from '../../app/navigation/navigationService';
import { useAuth } from '../auth/AuthProvider';
import { reconcileCardReminders } from './service';

function handleResponse(response: Notifications.NotificationResponse, authenticated: boolean) {
  const data = response.notification.request.content.data;
  if (
    !data
    || data.kind !== 'card-reminder'
    || typeof data.cardId !== 'string'
    || typeof data.boardId !== 'string'
    || typeof data.boardName !== 'string'
    || typeof data.workspaceId !== 'string'
  ) return;
  openReminderTarget({
    cardId: data.cardId,
    boardId: data.boardId,
    boardName: data.boardName,
    workspaceId: data.workspaceId,
  });
  flushReminderTarget(authenticated);
}

export function ReminderProvider({ children }: PropsWithChildren) {
  const auth = useAuth();

  useEffect(() => {
    if (auth.status !== 'authenticated') return undefined;
    void reconcileCardReminders();
    const appState = AppState.addEventListener('change', (state) => {
      if (state === 'active') void reconcileCardReminders();
    });
    const response = Notifications.addNotificationResponseReceivedListener((value) => {
      handleResponse(value, true);
    });
    void Notifications.getLastNotificationResponseAsync().then(async (value) => {
      if (value) {
        handleResponse(value, true);
        await Notifications.clearLastNotificationResponseAsync();
      }
    });
    return () => {
      appState.remove();
      response.remove();
    };
  }, [auth.status, auth.user?.id]);

  return children;
}
