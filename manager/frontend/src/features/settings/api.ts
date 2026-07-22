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

export function useCheckBrowserUpdate() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: () => api.checkBrowserUpdate(),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
      toast({ title: 'Browser information refreshed', tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Update check failed',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useBackups() {
  return useQuery({ queryKey: queryKeys.backups, queryFn: () => api.listBackups() });
}

export function useCreateBackup() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: () => api.createBackup(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.backups });
      toast({ title: 'Backup created', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Backup failed', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useRestoreBackup() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.restoreBackup(id),
    onSuccess: () => {
      queryClient.invalidateQueries();
      toast({ title: 'Backup restored', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Restore failed', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useDeleteBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteBackup(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.backups }),
  });
}
