import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { Settings } from '@/types/api';
import { useToast } from '@/components/ui/Toast';

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => api.getSettings(),
    staleTime: 30_000,
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (patch: Partial<Settings>) => api.updateSettings(patch),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
      queryClient.invalidateQueries({ queryKey: ['bootstrap'] });
      toast({ title: 'Settings saved', tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not save settings',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}
