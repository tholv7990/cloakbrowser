import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';

export function useTags() {
  return useQuery({ queryKey: queryKeys.tags, queryFn: () => api.listTags(), staleTime: 60_000 });
}

export function useCreateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; color?: string }) => api.createTag(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tags'] }),
  });
}

export function useWorkflowStatuses() {
  return useQuery({
    queryKey: queryKeys.statuses,
    queryFn: () => api.listWorkflowStatuses(),
    staleTime: 60_000,
  });
}
