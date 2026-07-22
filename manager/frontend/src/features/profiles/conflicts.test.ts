import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/http';
import { handleProfileConflict, PROFILE_CONFLICT_REVIEW_MESSAGE } from './conflicts';

describe('handleProfileConflict', () => {
  it('invalidates both profile lists and the loaded profile for explicit review', async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    expect(
      handleProfileConflict(
        queryClient,
        new ApiError(409, 'profile_conflict', 'stale', {
          current_profile: { id: 'profile-1' },
        }),
        'profile-1',
      ),
    ).toBe(true);
    expect(PROFILE_CONFLICT_REVIEW_MESSAGE).toMatch(/refresh.*review/i);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['profiles'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['profile', 'profile-1'] });
  });
});
