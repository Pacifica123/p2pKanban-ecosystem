import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getBoardAppearance,
  getMyAppearance,
  updateBoardAppearance,
  updateMyAppearance,
} from '@/features/appearance/api/appearance';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import type {
  BoardAppearanceSettings,
  UpdateBoardAppearanceRequest,
  UpdateUserAppearancePreferencesRequest,
  UserAppearancePreferences,
} from '@/shared/types/api';

export const myAppearanceQueryKey = (userId: string) => ['appearance', 'me', userId];
export const boardAppearanceQueryKey = (boardId?: string) => ['appearance', 'board', boardId];

export function useMyAppearanceQuery() {
  const { user } = useAuthSession();
  const userId = user?.id || 'anonymous';
  return useQuery({
    queryKey: myAppearanceQueryKey(userId),
    queryFn: getMyAppearance,
    enabled: Boolean(user?.id),
  });
}

export function useBoardAppearanceQuery(boardId?: string) {
  return useQuery({
    queryKey: boardAppearanceQueryKey(boardId),
    queryFn: () => getBoardAppearance(boardId!),
    enabled: Boolean(boardId),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

export function useUpdateMyAppearanceMutation() {
  const queryClient = useQueryClient();
  const { user } = useAuthSession();
  const userId = user?.id || 'anonymous';

  return useMutation({
    mutationFn: (input: UpdateUserAppearancePreferencesRequest) => updateMyAppearance(input),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: myAppearanceQueryKey(userId) });
      const previous = queryClient.getQueryData<UserAppearancePreferences>(myAppearanceQueryKey(userId));
      if (previous) {
        queryClient.setQueryData<UserAppearancePreferences>(myAppearanceQueryKey(userId), {
          ...previous,
          ...input,
          isCustomized: true,
          updatedAt: new Date().toISOString(),
        });
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) {
        queryClient.setQueryData(myAppearanceQueryKey(userId), context.previous);
      }
    },
    onSuccess: (data) => {
      queryClient.setQueryData(myAppearanceQueryKey(userId), data);
    },
  });
}

function mergeBoardAppearance(base: BoardAppearanceSettings, input: UpdateBoardAppearanceRequest): BoardAppearanceSettings {
  return {
    ...base,
    ...input,
    wallpaper: input.wallpaper || base.wallpaper,
    customProperties: input.customProperties || base.customProperties,
    isCustomized: true,
    updatedAt: new Date().toISOString(),
  };
}

export function useUpdateBoardAppearanceMutation(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateBoardAppearanceRequest) => updateBoardAppearance(boardId!, input),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardAppearanceQueryKey(boardId) });
      const previous = queryClient.getQueryData<BoardAppearanceSettings>(boardAppearanceQueryKey(boardId));
      if (previous) {
        queryClient.setQueryData<BoardAppearanceSettings>(boardAppearanceQueryKey(boardId), mergeBoardAppearance(previous, input));
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) {
        queryClient.setQueryData(boardAppearanceQueryKey(boardId), context.previous);
      }
    },
    onSuccess: (data) => {
      queryClient.setQueryData(boardAppearanceQueryKey(boardId), data);
    },
  });
}
