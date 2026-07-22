import { describe, expect, it, vi } from 'vitest';
import { persistProfileWithExtensions } from './persistence';

describe('persistProfileWithExtensions', () => {
  it('retries only extension assignment after a profile was already saved', async () => {
    const saveProfile = vi.fn().mockResolvedValue({ id: 'profile-1' });
    const assignExtensions = vi
      .fn()
      .mockRejectedValueOnce(new Error('assignment failed'))
      .mockResolvedValueOnce({ extension_ids: ['extension-1'] });

    const first = await persistProfileWithExtensions({
      savedProfileId: null,
      extensionIds: ['extension-1'],
      saveProfile,
      assignExtensions,
    });
    expect(first).toEqual({ profileId: 'profile-1', assignmentComplete: false });

    const second = await persistProfileWithExtensions({
      savedProfileId: first.profileId,
      extensionIds: ['extension-1'],
      saveProfile,
      assignExtensions,
    });
    expect(second).toEqual({ profileId: 'profile-1', assignmentComplete: true });
    expect(saveProfile).toHaveBeenCalledTimes(1);
    expect(assignExtensions).toHaveBeenCalledTimes(2);
  });
});
