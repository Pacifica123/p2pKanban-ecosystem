import { createNavigationContainerRef } from '@react-navigation/native';

import type { RootStackParamList } from './types';

export interface ReminderNavigationTarget {
  workspaceId: string;
  boardId: string;
  boardName: string;
  cardId: string;
}

export const navigationRef = createNavigationContainerRef<RootStackParamList>();
let pendingReminderTarget: ReminderNavigationTarget | null = null;

export function openReminderTarget(target: ReminderNavigationTarget) {
  pendingReminderTarget = target;
}

export function flushReminderTarget(authenticated: boolean) {
  if (!authenticated || !navigationRef.isReady() || !pendingReminderTarget) return;
  const target = pendingReminderTarget;
  pendingReminderTarget = null;
  navigationRef.navigate('Board', {
    workspaceId: target.workspaceId,
    boardId: target.boardId,
    boardName: target.boardName,
    focusCardId: target.cardId,
  });
}
