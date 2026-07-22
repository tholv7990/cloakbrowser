import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';

export function useResources(enabled = true) {
  return useQuery({
    queryKey: queryKeys.resources,
    queryFn: () => api.getResources(),
    enabled,
    refetchInterval: 2000,
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 0,
  });
}

export function useSessions(limit = 25) {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: () => api.listSessions(limit),
    staleTime: 10_000,
  });
}
