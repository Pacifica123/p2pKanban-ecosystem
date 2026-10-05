import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  boardActivityQueryKey,
  boardProductivityQueryKey,
  cardActivityQueryKey,
} from '@/features/activity/hooks/useActivity';
import { cardDetailQueryKey, cardsQueryKey } from '@/features/cards/hooks/useCards';
import {
  createChecklist,
  createChecklistItem,
  deleteChecklist,
  deleteChecklistItem,
  getCardChecklists,
  updateChecklist,
  updateChecklistItem,
} from '@/features/checklists/api/checklists';

export const cardChecklistsQueryKey = (cardId?: string) => ['card-checklists', cardId];

function invalidateChecklistSurface(queryClient: ReturnType<typeof useQueryClient>, boardId?: string, cardId?: string) {
  void queryClient.invalidateQueries({ queryKey: cardsQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: cardDetailQueryKey(cardId) });
  void queryClient.invalidateQueries({ queryKey: cardChecklistsQueryKey(cardId) });
  void queryClient.invalidateQueries({ queryKey: boardActivityQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: boardProductivityQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: cardActivityQueryKey(cardId) });
}

export function useCardChecklistsQuery(cardId?: string) {
  return useQuery({
    queryKey: cardChecklistsQueryKey(cardId),
    queryFn: () => getCardChecklists(cardId!),
    enabled: Boolean(cardId),
    refetchInterval: 4_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateChecklistMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { title: string; position?: number | null }) => createChecklist(cardId!, input),
    onSuccess: () => invalidateChecklistSurface(queryClient, boardId, cardId),
  });
}

export function useUpdateChecklistMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { checklistId: string; input: { title?: string; position?: number | null } }) =>
      updateChecklist(variables.checklistId, variables.input),
    onSuccess: () => invalidateChecklistSurface(queryClient, boardId, cardId),
  });
}

export function useDeleteChecklistMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (checklistId: string) => deleteChecklist(checklistId),
    onSuccess: () => invalidateChecklistSurface(queryClient, boardId, cardId),
  });
}

export function useCreateChecklistItemMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { checklistId: string; title: string; position?: number | null }) =>
      createChecklistItem(variables.checklistId, { title: variables.title, position: variables.position }),
    onSuccess: () => invalidateChecklistSurface(queryClient, boardId, cardId),
  });
}

export function useUpdateChecklistItemMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { itemId: string; input: { title?: string; position?: number | null; isDone?: boolean | null } }) =>
      updateChecklistItem(variables.itemId, variables.input),
    onSuccess: () => invalidateChecklistSurface(queryClient, boardId, cardId),
  });
}

export function useDeleteChecklistItemMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId: string) => deleteChecklistItem(itemId),
    onSuccess: () => invalidateChecklistSurface(queryClient, boardId, cardId),
  });
}
