import { describe, expect, it, vi } from 'vitest';
import { persistProfileWithExtensions } from './persistence';

describe('persistProfileWithExtensions', () => {
  it('updates an already-created profile with later form edits before retrying assignment', async () => {
    let currentName = 'initial name';
    const saveProfile = vi.fn().mockImplementation(async () => ({
      id: 'profile-1',
      name: currentName,
    }));
    const updateSavedProfile = vi.fn().mockImplementation(async (savedProfile) => ({
      ...savedProfile,
      name: currentName,
    }));
    const assignExtensions = vi
      .fn()
      .mockRejectedValueOnce(new Error('assignment failed'))
      .mockResolvedValueOnce({ extension_ids: ['extension-1'] });

    const first = await persistProfileWithExtensions({
      savedProfile: null,
      extensionIds: ['extension-1'],
      saveProfile,
      updateSavedProfile,
      assignExtensions,
    });
    expect(first).toEqual({
      profile: { id: 'profile-1', name: 'initial name' },
      assignmentComplete: false,
    });

    currentName = 'edited after assignment failure';
    const second = await persistProfileWithExtensions({
      savedProfile: first.profile,
      extensionIds: ['extension-1'],
      saveProfile,
      updateSavedProfile,
      assignExtensions,
    });
    expect(second).toEqual({
      profile: { id: 'profile-1', name: 'edited after assignment failure' },
      assignmentComplete: true,
    });
    expect(saveProfile).toHaveBeenCalledTimes(1);
    expect(updateSavedProfile).toHaveBeenCalledTimes(1);
    expect(assignExtensions).toHaveBeenCalledTimes(2);
  });

  it('carries the newest saved baseline across repeated assignment failures', async () => {
    let revision = 1;
    const saveProfile = vi.fn().mockResolvedValue({ id: 'profile-2', revision });
    const updateSavedProfile = vi.fn().mockImplementation(async (savedProfile) => ({
      ...savedProfile,
      revision,
    }));
    const assignExtensions = vi
      .fn()
      .mockRejectedValueOnce(new Error('first assignment failure'))
      .mockRejectedValueOnce(new Error('second assignment failure'))
      .mockResolvedValueOnce({ extension_ids: ['extension-2'] });

    const first = await persistProfileWithExtensions({
      savedProfile: null,
      extensionIds: ['extension-2'],
      saveProfile,
      updateSavedProfile,
      assignExtensions,
    });
    revision = 2;
    const second = await persistProfileWithExtensions({
      savedProfile: first.profile,
      extensionIds: ['extension-2'],
      saveProfile,
      updateSavedProfile,
      assignExtensions,
    });
    expect(second).toMatchObject({ profile: { revision: 2 }, assignmentComplete: false });

    revision = 3;
    const third = await persistProfileWithExtensions({
      savedProfile: second.profile,
      extensionIds: ['extension-2'],
      saveProfile,
      updateSavedProfile,
      assignExtensions,
    });
    expect(third).toMatchObject({ profile: { revision: 3 }, assignmentComplete: true });
    expect(saveProfile).toHaveBeenCalledTimes(1);
    expect(updateSavedProfile).toHaveBeenNthCalledWith(2, expect.objectContaining({ revision: 2 }));
  });
});
