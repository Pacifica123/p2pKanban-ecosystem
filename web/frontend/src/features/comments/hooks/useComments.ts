import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { boardActivityQueryKey, cardActivityQueryKey } from '@/features/activity/hooks/useActivity';
import { cardDetailQueryKey, cardsQueryKey } from '@/features/cards/hooks/useCards';
import { createComment, deleteComment, getCardComments, updateComment } from '@/features/comments/api/comments';

export const cardCommentsQueryKey = (cardId?: string) => ['card-comments', cardId];

function invalidateCommentSurface(queryClient: ReturnType<typeof useQueryClient>, boardId?: string, cardId?: string) {
  void queryClient.invalidateQueries({ queryKey: cardsQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: cardDetailQueryKey(cardId) });
  void queryClient.invalidateQueries({ queryKey: cardCommentsQueryKey(cardId) });
  void queryClient.invalidateQueries({ queryKey: boardActivityQueryKey(boardId) });
  void queryClient.invalidateQueries({ queryKey: cardActivityQueryKey(cardId) });
}

export function useCardCommentsQuery(cardId?: string) {
  return useQuery({
    queryKey: cardCommentsQueryKey(cardId),
    queryFn: () => getCardComments(cardId!),
    enabled: Boolean(cardId),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateCommentMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => createComment(cardId!, { body }),
    onSuccess: () => invalidateCommentSurface(queryClient, boardId, cardId),
  });
}

export function useUpdateCommentMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { commentId: string; body: string }) => updateComment(variables.commentId, { body: variables.body }),
    onSuccess: () => invalidateCommentSurface(queryClient, boardId, cardId),
  });
}

export function useDeleteCommentMutation(boardId?: string, cardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (commentId: string) => deleteComment(commentId),
    onSuccess: () => invalidateCommentSurface(queryClient, boardId, cardId),
  });
}
