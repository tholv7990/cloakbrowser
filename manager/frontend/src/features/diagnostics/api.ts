import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import { useToast } from '@/components/ui/Toast';

export function useDiagnostics() {
  return useQuery({
    queryKey: queryKeys.diagnostics,
    queryFn: () => api.listDiagnostics(),
    staleTime: 15_000,
  });
}

export function useRunDirectGoogleControl() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: () => api.runDirectGoogleControl(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['diagnostics'] });
      toast({ title: 'Direct Google control finished', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Control run failed', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useRunPixelscan() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (profileId: string) => api.runPixelscan(profileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['diagnostics'] });
      toast({ title: 'Pixelscan run finished', tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Pixelscan run failed',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}
