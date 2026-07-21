import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';

export function useTags() {
  return useQuery({ queryKey: queryKeys.tags, queryFn: () => api.listTags(), staleTime: 60_000 });
}

export function useWorkflowStatuses() {
  return useQuery({
    queryKey: queryKeys.statuses,
    queryFn: () => api.listWorkflowStatuses(),
    staleTime: 60_000,
  });
}
