import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createColumn, deleteColumn, getColumns, updateColumn } from '@/features/columns/api/columns';
import { boardProductivityQueryKey } from '@/features/activity/hooks/useActivity';

export const columnsQueryKey = (boardId?: string) => ['columns', boardId];

export function useColumnsQuery(boardId?: string) {
  return useQuery({
    queryKey: columnsQueryKey(boardId),
    queryFn: () => getColumns(boardId!),
    enabled: Boolean(boardId),
    refetchInterval: 6_000,
    refetchIntervalInBackground: false,
  });
}

export function useCreateColumnMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; description?: string }) => createColumn(boardId!, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: columnsQueryKey(boardId) });
      void queryClient.invalidateQueries({ queryKey: boardProductivityQueryKey(boardId) });
    },
  });
}

export function useUpdateColumnMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ columnId, input }: { columnId: string; input: { name?: string; description?: string } }) =>
      updateColumn(boardId!, columnId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: columnsQueryKey(boardId) });
      void queryClient.invalidateQueries({ queryKey: boardProductivityQueryKey(boardId) });
    },
  });
}

export function useDeleteColumnMutation(boardId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (columnId: string) => deleteColumn(boardId!, columnId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: columnsQueryKey(boardId) });
      void queryClient.invalidateQueries({ queryKey: boardProductivityQueryKey(boardId) });
    },
  });
}
