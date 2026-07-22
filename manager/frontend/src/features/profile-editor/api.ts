import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { ProfileCreatePayload, ProfileUpdatePayload } from '@/types/api';
import { useToast } from '@/components/ui/Toast';
import {
  handleProfileConflict,
  PROFILE_CONFLICT_REVIEW_MESSAGE,
} from '@/features/profiles/conflicts';

export function useProfile(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.profile(id) : ['profile', 'none'],
    queryFn: () => api.getProfile(id!),
    enabled: Boolean(id),
  });
}

export function useCreateProfile() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: ProfileCreatePayload) => api.createProfile(payload),
    onSuccess: (profile) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
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

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ProfileUpdatePayload }) =>
      api.updateProfile(id, payload),
    onSuccess: (profile) => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['profile', profile.id] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      toast({ title: 'Profile saved', description: profile.name, tone: 'success' });
    },
    onError: (error, variables) => {
      const conflict = handleProfileConflict(queryClient, error, variables.id);
      toast({
        title: 'Could not save profile',
        description: conflict ? PROFILE_CONFLICT_REVIEW_MESSAGE : (error as Error).message,
        tone: 'danger',
      });
    },
  });
}
