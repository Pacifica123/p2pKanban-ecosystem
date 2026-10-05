import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  archiveCard,
  createCard,
  deleteCard,
  getCard,
  getCards,
  hideCardLocally,
  moveCard,
  reorderColumnCards,
  unarchiveCard,
  unhideCardLocally,
  updateCard,
  type CardLocalVisibility,
} from '@/features/cards/api/cards';
import { columnsQueryKey } from '@/features/columns/hooks/useColumns';
import {
  boardActivityQueryKey,
  boardProductivityQueryKey,
  cardActivityQueryKey,
} from '@/features/activity/hooks/useActivity';
import type { CardPriority } from '@/shared/types/api';

export const cardsQueryKey = (boardId?: string, localVisibility: CardLocalVisibility = 'visible') =>
  ['cards', boardId, localVisibility];
export const cardDetailQueryKey = (cardId?: string) => ['card', cardId];

function invalidateBoardSurface(queryClient: ReturnType<typeof useQueryClient>, boardId?: string, cardId?: string) {
  void queryClient.invalidateQueries({ queryKey: ['cards', boardId] });
  void queryClient.invalidateQueries({ queryKey: columnsQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: boardActivityQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: boardProductivityQueryKey(boardId) });
  if (cardId) {
    void queryClient.invalidateQueries({ queryKey: cardDetailQueryKey(cardId) });
    void queryClient.invalidateQueries({ queryKey: cardActivityQueryKey(cardId) });
  }
}

export function useCardsQuery(
  boardId?: string,
  localVisibility: CardLocalVisibility = 'visible',
) {
  return useQuery({
    queryKey: cardsQueryKey(boardId, localVisibility),
    queryFn: () => getCards(boardId!, localVisibility),
    enabled: Boolean(boardId),
    refetchInterval: 3_000,
    refetchIntervalInBackground: false,
  });
}

export function useCardQuery(cardId?: string) {
  return useQuery({
    queryKey: cardDetailQueryKey(cardId),
    queryFn: () => getCard(cardId!),
    enabled: Boolean(cardId),
    refetchInterval: 4_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateCardMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { title: string; description?: string; columnId: string }) => createCard(boardId!, input),
    onSuccess: (card) => {
      invalidateBoardSurface(queryClient, boardId, card.id);
    },
  });
}

export function useUpdateCardMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { title?: string; description?: string | null; priority?: CardPriority }) =>
      updateCard(cardId!, input),
    onSuccess: () => {
      invalidateBoardSurface(queryClient, boardId, cardId);
    },
  });
}

export function useMoveCardMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { cardId?: string; targetColumnId: string; position?: number | null }) =>
      moveCard(variables.cardId || cardId!, {
        targetColumnId: variables.targetColumnId,
        position: variables.position,
      }),
    onSuccess: (card, variables) => {
      invalidateBoardSurface(queryClient, boardId, variables.cardId || cardId || card.id);
    },
  });
}

export function useReorderColumnCardsMutation(boardId?: string, columnId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { columnId?: string; items: Array<{ cardId: string; position: number }> }) =>
      reorderColumnCards(variables.columnId || columnId!, {
        items: variables.items,
      }),
    onSuccess: () => {
      invalidateBoardSurface(queryClient, boardId);
    },
  });
}

export function useArchiveCardMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => archiveCard(cardId!),
    onSuccess: () => {
      invalidateBoardSurface(queryClient, boardId, cardId);
    },
  });
}

export function useUnarchiveCardMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unarchiveCard(cardId!),
    onSuccess: () => {
      invalidateBoardSurface(queryClient, boardId, cardId);
    },
  });
}

export function useDeleteCardMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => deleteCard(cardId!),
    onSuccess: () => {
      invalidateBoardSurface(queryClient, boardId, cardId);
    },
  });
}

export function useHideCardLocallyMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => hideCardLocally(cardId!),
    onSuccess: () => {
      invalidateBoardSurface(queryClient, boardId, cardId);
    },
  });
}

export function useUnhideCardLocallyMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cardId: string) => unhideCardLocally(cardId),
    onSuccess: (card) => {
      invalidateBoardSurface(queryClient, boardId, card.id);
    },
  });
}
