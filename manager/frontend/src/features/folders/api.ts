import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import { useToast } from '@/components/ui/Toast';

export function useFolders() {
  return useQuery({
    queryKey: queryKeys.folders,
    queryFn: () => api.listFolders(),
    staleTime: 30_000,
  });
}

function useFolderInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['folders'] });
    queryClient.invalidateQueries({ queryKey: ['bootstrap'] });
  };
}

export function useCreateFolder() {
  const invalidate = useFolderInvalidation();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (name: string) => api.createFolder(name),
    onSuccess: (folder) => {
      invalidate();
      toast({ title: 'Folder created', description: folder.name, tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not create folder',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useRenameFolder() {
  const invalidate = useFolderInvalidation();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.renameFolder(id, name),
    onSuccess: invalidate,
    onError: (error) =>
      toast({
        title: 'Could not rename folder',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useReorderFolders() {
  const invalidate = useFolderInvalidation();
  return useMutation({
    mutationFn: (orderedIds: string[]) => api.reorderFolders(orderedIds),
    onSuccess: invalidate,
  });
}

export function useDeleteFolder() {
  const invalidate = useFolderInvalidation();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.deleteFolder(id),
    onSuccess: () => {
      invalidate();
      toast({
        title: 'Folder deleted',
        description: 'Its profiles are now unfiled.',
        tone: 'success',
      });
    },
    onError: (error) =>
      toast({
        title: 'Could not delete folder',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}
