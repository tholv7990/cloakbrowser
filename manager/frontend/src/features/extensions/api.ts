import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';

export function useExtensions() {
  return useQuery({ queryKey: queryKeys.extensions, queryFn: () => api.listExtensions() });
}

function useExtensionMutation<T>(mutationFn: (value: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.extensions }),
  });
}

export function useRegisterExtension() {
  return useExtensionMutation((directory: string) => api.registerExtension(directory));
}

export function useUpdateExtension() {
  return useExtensionMutation(
    ({ id, patch }: { id: string; patch: { enabled?: boolean; refresh?: boolean } }) =>
      api.updateExtension(id, patch),
  );
}

export function useUnregisterExtension() {
  return useExtensionMutation((id: string) => api.unregisterExtension(id));
}
