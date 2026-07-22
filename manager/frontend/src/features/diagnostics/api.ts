import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { DiagnosticKind, DiagnosticListParams } from '@/types/api';

export function useDiagnostics(params: DiagnosticListParams = {}) {
  return useQuery({
    queryKey: [...queryKeys.diagnostics, params],
    queryFn: () => api.listDiagnostics(params),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => run.status === 'queued' || run.status === 'running')
        ? 2_000
        : false,
  });
}

export function useRunDiagnostic() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, profileId }: { kind: DiagnosticKind; profileId: string | null }) =>
      kind === 'direct_google_control'
        ? api.runDirectGoogleControl()
        : api.runDiagnostic(kind, profileId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.diagnostics }),
  });
}

export function useCancelDiagnostic() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelDiagnostic(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.diagnostics }),
  });
}

/** Compatibility exports for existing callers. */
export function useRunDirectGoogleControl() {
  const mutation = useRunDiagnostic();
  return {
    ...mutation,
    mutate: () => mutation.mutate({ kind: 'direct_google_control', profileId: null }),
  };
}

export function useRunPixelscan() {
  const mutation = useRunDiagnostic();
  return {
    ...mutation,
    mutate: (profileId: string) => mutation.mutate({ kind: 'pixelscan', profileId }),
  };
}

export { useResources, useSessions } from './supportApi';
