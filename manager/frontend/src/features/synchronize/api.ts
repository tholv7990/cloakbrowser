import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { ArrangeRequest, SyncStartRequest, SyncStatus } from '@/types/api';

export function useMonitors() {
  return useQuery({ queryKey: queryKeys.monitors, queryFn: () => api.getMonitors() });
}

export function useArrangeWindows() {
  return useMutation({ mutationFn: (payload: ArrangeRequest) => api.arrangeWindows(payload) });
}

export function useSyncStatus() {
  return useQuery({
    queryKey: queryKeys.syncStatus,
    queryFn: () => api.getSyncStatus(),
    // A session can end on its own (a synced browser closed), so keep this fresh.
    refetchInterval: 5000,
  });
}

export function useStartInputSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: SyncStartRequest) => api.startInputSync(payload),
    onSuccess: (status: SyncStatus) => client.setQueryData(queryKeys.syncStatus, status),
  });
}

export function useStopInputSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.stopInputSync(),
    onSuccess: (status: SyncStatus) => client.setQueryData(queryKeys.syncStatus, status),
  });
}
