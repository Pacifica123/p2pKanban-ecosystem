import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { boardActivityQueryKey, cardActivityQueryKey } from '@/features/activity/hooks/useActivity';
import { cardDetailQueryKey, cardsQueryKey } from '@/features/cards/hooks/useCards';
import { createBoardLabel, deleteBoardLabel, getBoardLabels, replaceCardLabels, updateBoardLabel } from '@/features/labels/api/labels';

export const boardLabelsQueryKey = (boardId?: string) => ['board-labels', boardId];

function invalidateLabelSurface(queryClient: ReturnType<typeof useQueryClient>, boardId?: string, cardId?: string) {
  void queryClient.invalidateQueries({ queryKey: boardLabelsQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: cardsQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: boardActivityQueryKey(boardId) });
  if (cardId) {
    void queryClient.invalidateQueries({ queryKey: cardDetailQueryKey(cardId) });
    void queryClient.invalidateQueries({ queryKey: cardActivityQueryKey(cardId) });
  }
}

export function useBoardLabelsQuery(boardId?: string) {
  return useQuery({
    queryKey: boardLabelsQueryKey(boardId),
    queryFn: () => getBoardLabels(boardId!),
    enabled: Boolean(boardId),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateBoardLabelMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; color: string; description?: string | null }) => createBoardLabel(boardId!, input),
    onSuccess: () => invalidateLabelSurface(queryClient, boardId),
  });
}

export function useUpdateBoardLabelMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { labelId: string; input: { name?: string; color?: string; description?: string | null } }) =>
      updateBoardLabel(variables.labelId, variables.input),
    onSuccess: () => invalidateLabelSurface(queryClient, boardId),
  });
}

export function useDeleteBoardLabelMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (labelId: string) => deleteBoardLabel(labelId),
    onSuccess: () => invalidateLabelSurface(queryClient, boardId),
  });
}

export function useReplaceCardLabelsMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (labelIds: string[]) => replaceCardLabels(cardId!, labelIds),
    onSuccess: () => invalidateLabelSurface(queryClient, boardId, cardId),
  });
}
