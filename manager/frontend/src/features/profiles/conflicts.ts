import type { QueryClient } from '@tanstack/react-query';
import { ApiError, queryKeys } from '@/api';

export const PROFILE_CONFLICT_REVIEW_MESSAGE =
  'This profile changed elsewhere. The latest values are being refreshed; review them before saving again.';

/** Refresh both list and detail caches after an optimistic-concurrency conflict. */
export function handleProfileConflict(
  queryClient: QueryClient,
  error: unknown,
  profileId: string,
): boolean {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== 'profile_conflict') {
    return false;
  }
  void queryClient.invalidateQueries({ queryKey: queryKeys.profilesRoot });
  void queryClient.invalidateQueries({ queryKey: queryKeys.profile(profileId) });
  return true;
}
