import { apiRequest } from '@/shared/api/client';
import type {
  BoardAppearanceSettings,
  UpdateBoardAppearanceRequest,
  UpdateUserAppearancePreferencesRequest,
  UserAppearancePreferences,
} from '@/shared/types/api';

function normalizeUserAppearance(
  value: UserAppearancePreferences,
): UserAppearancePreferences {
  return {
    ...value,
    checklistItemSubmitMode: value.checklistItemSubmitMode || 'ctrl_enter',
    cardDetailsMode: value.cardDetailsMode || 'drawer',
  };
}

export async function getMyAppearance() {
  return normalizeUserAppearance(
    await apiRequest<UserAppearancePreferences>('/me/appearance'),
  );
}

export async function updateMyAppearance(input: UpdateUserAppearancePreferencesRequest) {
  const value = await apiRequest<UserAppearancePreferences>('/me/appearance', {
    method: 'PUT',
    body: JSON.stringify(input),
  });
  return normalizeUserAppearance(value);
}

export function getBoardAppearance(boardId: string) {
  return apiRequest<BoardAppearanceSettings>(`/boards/${boardId}/appearance`);
}

export function updateBoardAppearance(boardId: string, input: UpdateBoardAppearanceRequest) {
  return apiRequest<BoardAppearanceSettings>(`/boards/${boardId}/appearance`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}
