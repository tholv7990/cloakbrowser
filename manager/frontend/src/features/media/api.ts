import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { CreateMediaAssetPayload, MediaSettings } from '@/types/api';
import { useToast } from '@/components/ui/Toast';

export function useMediaSettings() {
  return useQuery({ queryKey: queryKeys.mediaSettings, queryFn: () => api.getMediaSettings() });
}

export function useUpdateMediaSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<MediaSettings>) => api.updateMediaSettings(patch),
    onSuccess: (settings) => queryClient.setQueryData(queryKeys.mediaSettings, settings),
  });
}

export function useMediaAssets() {
  return useQuery({ queryKey: queryKeys.mediaAssets, queryFn: () => api.listMediaAssets() });
}

export function useCreateMediaAsset() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: CreateMediaAssetPayload) => api.createMediaAsset(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.mediaAssets });
      toast({ title: 'Media asset added', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Could not add asset', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useDeleteMediaAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteMediaAsset(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.mediaAssets }),
  });
}
