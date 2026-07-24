import { useMutation, useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { ArrangeRequest } from '@/types/api';

export function useMonitors() {
  return useQuery({ queryKey: queryKeys.monitors, queryFn: () => api.getMonitors() });
}

export function useArrangeWindows() {
  return useMutation({ mutationFn: (payload: ArrangeRequest) => api.arrangeWindows(payload) });
}
