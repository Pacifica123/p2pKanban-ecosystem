import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { archiveBoard, createBoard, getBoard, getBoards, updateBoard } from '@/features/boards/api/boards';

export const boardsQueryKey = (workspaceId?: string) => ['boards', workspaceId];
export const boardDetailQueryKey = (boardId?: string) => ['board', boardId];

export function useBoardsQuery(workspaceId?: string) {
  return useQuery({
    queryKey: boardsQueryKey(workspaceId),
    queryFn: () => getBoards(workspaceId!),
    enabled: Boolean(workspaceId),
    refetchInterval: 6_000,
    refetchIntervalInBackground: false,
  });
}

export function useBoardQuery(boardId?: string) {
  return useQuery({
    queryKey: boardDetailQueryKey(boardId),
    queryFn: () => getBoard(boardId!),
    enabled: Boolean(boardId),
    refetchInterval: 6_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateBoardMutation(workspaceId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; description?: string }) => createBoard(workspaceId!, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: boardsQueryKey(workspaceId) });
    },
  });
}

export function useUpdateBoardMutation(workspaceId?: string, boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: { boardId?: string; input: { name?: string; description?: string } }) =>
      updateBoard(variables.boardId || boardId!, variables.input),
    onSuccess: (_data, variables) => {
      const resolvedBoardId = variables.boardId || boardId;
      void queryClient.invalidateQueries({ queryKey: boardsQueryKey(workspaceId) });
      void queryClient.invalidateQueries({ queryKey: boardDetailQueryKey(resolvedBoardId) });
    },
  });
}

export function useArchiveBoardMutation(workspaceId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (boardId: string) => archiveBoard(boardId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: boardsQueryKey(workspaceId) });
    },
  });
}
