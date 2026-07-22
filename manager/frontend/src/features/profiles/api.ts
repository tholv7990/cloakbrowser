import { useEffect, useRef, useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type {
  BulkProfileRequest,
  Paginated,
  ProfileListParams,
  ProfileLogEntry,
  ProfileRead,
  ProfileWrite,
  RuntimeState,
} from '@/types/api';
import { useToast } from '@/components/ui/Toast';
import { emptyProfileWrite } from './view';
import { handleProfileConflict, PROFILE_CONFLICT_REVIEW_MESSAGE } from './conflicts';
import { mergeProfileLogTail } from './logTail';

export function useProfiles(params: ProfileListParams) {
  return useQuery({
    queryKey: queryKeys.profiles(params),
    queryFn: () => api.listProfiles(params),
    placeholderData: keepPreviousData,
  });
}

function patchInLists(
  queryClient: QueryClient,
  id: string,
  updater: (profile: ProfileRead) => ProfileRead,
): void {
  queryClient.setQueriesData<Paginated<ProfileRead>>({ queryKey: ['profiles'] }, (old) => {
    if (!old?.items) return old;
    return { ...old, items: old.items.map((p) => (p.id === id ? updater(p) : p)) };
  });
}

function removeFromLists(queryClient: QueryClient, id: string): void {
  queryClient.setQueriesData<Paginated<ProfileRead>>({ queryKey: ['profiles'] }, (old) => {
    if (!old?.items) return old;
    return {
      ...old,
      items: old.items.filter((p) => p.id !== id),
      total: Math.max(0, old.total - 1),
    };
  });
}

/**
 * Optimistic runtime transition. Start/stop are fire-and-forget (the backend
 * returns a runtime session, not a profile); the authoritative state arrives via
 * the runtime snapshot over the WebSocket, with a refetch as a fallback.
 */
function useRuntimeTransition(
  action: (id: string) => Promise<void>,
  optimistic: RuntimeState,
  failureVerb: string,
) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: action,
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: ['profiles'] });
      const snapshot = queryClient.getQueriesData<Paginated<ProfileRead>>({
        queryKey: ['profiles'],
      });
      patchInLists(queryClient, id, (p) => ({ ...p, runtime_state: optimistic }));
      return { snapshot };
    },
    onError: (error, _id, context) => {
      context?.snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data));
      toast({
        title: `Could not ${failureVerb} profile`,
        description: (error as Error).message,
        tone: 'danger',
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      queryClient.invalidateQueries({ queryKey: ['bootstrap'] });
    },
  });
}

export function useStartProfile() {
  return useRuntimeTransition((id) => api.startProfile(id), 'starting', 'start');
}

export function useStopProfile() {
  return useRuntimeTransition((id) => api.stopProfile(id), 'stopping', 'stop');
}

export function usePinToggle() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      api.bulkProfiles({ action: pinned ? 'pin' : 'unpin', ids: [id] }),
    onMutate: async ({ id, pinned }) => {
      await queryClient.cancelQueries({ queryKey: ['profiles'] });
      const snapshot = queryClient.getQueriesData<Paginated<ProfileRead>>({
        queryKey: ['profiles'],
      });
      patchInLists(queryClient, id, (p) => ({ ...p, pinned }));
      return { snapshot };
    },
    onError: (error, _vars, context) => {
      context?.snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data));
      toast({
        title: 'Could not update pin',
        description: (error as Error).message,
        tone: 'danger',
      });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['profiles'] }),
  });
}

export function useMoveToTrash() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.moveProfileToTrash(id),
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: ['profiles'] });
      const snapshot = queryClient.getQueriesData<Paginated<ProfileRead>>({
        queryKey: ['profiles'],
      });
      removeFromLists(queryClient, id);
      return { snapshot };
    },
    onError: (error, _id, context) => {
      context?.snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data));
      toast({
        title: 'Could not move to trash',
        description: (error as Error).message,
        tone: 'danger',
      });
    },
    onSuccess: () => toast({ title: 'Profile moved to trash', tone: 'success' }),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
    },
  });
}

/**
 * Inline edit of one or more profile fields from the table. The backend applies
 * only provided fields and rejects stale `updated_at` values.
 */
export function useUpdateProfileInline() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ read, changes }: { read: ProfileRead; changes: Partial<ProfileWrite> }) =>
      api.updateProfile(read.id, { expected_updated_at: read.updated_at, ...changes }),
    onMutate: async ({ read, changes }) => {
      await queryClient.cancelQueries({ queryKey: ['profiles'] });
      const snapshot = queryClient.getQueriesData<Paginated<ProfileRead>>({
        queryKey: ['profiles'],
      });
      patchInLists(queryClient, read.id, (p) => ({ ...p, ...changes }) as ProfileRead);
      return { snapshot };
    },
    onError: (error, variables, context) => {
      context?.snapshot?.forEach(([key, data]) => queryClient.setQueryData(key, data));
      const conflict = handleProfileConflict(queryClient, error, variables.read.id);
      toast({
        title: 'Could not save change',
        description: conflict ? PROFILE_CONFLICT_REVIEW_MESSAGE : (error as Error).message,
        tone: 'danger',
      });
    },
    onSuccess: (profile) => patchInLists(queryClient, profile.id, () => profile),
  });
}

export function useDuplicateProfile() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.duplicateProfile(id),
    onSuccess: (profile) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      toast({ title: 'Profile duplicated', description: profile.name, tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not duplicate profile',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useRegenerateFingerprint() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.regenerateFingerprint(id),
    onSuccess: (profile) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['profile', profile.id] });
      toast({
        title: 'New fingerprint generated',
        description: `Seed ${profile.fingerprint_seed}`,
        tone: 'success',
      });
    },
    onError: (error) =>
      toast({
        title: 'Could not regenerate fingerprint',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useFocusWindow() {
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.focusWindow(id),
    onError: (error) =>
      toast({
        title: 'Could not focus the window',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useBulkAction() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (request: BulkProfileRequest) => api.bulkProfiles(request),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      toast({
        title: `Updated ${result.count} profile${result.count === 1 ? '' : 's'}`,
        tone: 'success',
      });
    },
    onError: (error) =>
      toast({ title: 'Bulk action failed', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useImportCookies() {
  return useMutation({
    mutationFn: ({
      id,
      format,
      content,
    }: {
      id: string;
      format: 'netscape' | 'json' | 'playwright';
      content: string;
    }) => api.importCookies(id, { format, content }),
  });
}

export function useProfileLogs(id: string | null, page = 1, pageSize = 20) {
  return useQuery({
    queryKey: id
      ? [...queryKeys.profileLogs(id), { page, page_size: pageSize }]
      : ['profile', 'logs', 'none'],
    queryFn: () => api.getProfileLogs(id!, { page, page_size: pageSize }),
    enabled: Boolean(id),
  });
}

export function useProfileLogTail(id: string | null, limit = 20, enabled = true) {
  const cursor = useRef<string | null>(null);
  const [items, setItems] = useState<ProfileLogEntry[]>([]);

  useEffect(() => {
    cursor.current = null;
    setItems([]);
  }, [id, limit]);

  const query = useQuery({
    queryKey: id
      ? [...queryKeys.profileLogs(id), 'tail', { limit }]
      : ['profile', 'logs', 'tail', 'none'],
    queryFn: () =>
      api.getProfileLogTail(id!, {
        cursor: cursor.current ?? undefined,
        limit,
      }),
    enabled: Boolean(id) && enabled,
    refetchInterval: enabled ? 2_000 : false,
  });

  useEffect(() => {
    if (!query.data) return;
    setItems((current) => mergeProfileLogTail(current, query.data, limit));
    cursor.current = query.data.next_cursor;
  }, [query.data, limit]);

  return { ...query, items };
}

export function useQuickCreate() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: () =>
      api.quickCreateProfile(
        emptyProfileWrite(`quick-profile-${Math.floor(Math.random() * 9000) + 1000}`),
      ),
    onSuccess: (profile) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      toast({ title: 'Profile created', description: profile.name, tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not create profile',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}
