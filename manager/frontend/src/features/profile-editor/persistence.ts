interface IdentifiedProfile {
  id: string;
}

interface PersistProfileWithExtensionsInput<TProfile extends IdentifiedProfile> {
  savedProfile: TProfile | null;
  extensionIds: string[];
  saveProfile: () => Promise<TProfile>;
  updateSavedProfile: (savedProfile: TProfile) => Promise<TProfile>;
  assignExtensions: (profileId: string, extensionIds: string[]) => Promise<unknown>;
}

export interface ProfilePersistenceResult<TProfile extends IdentifiedProfile> {
  profile: TProfile;
  assignmentComplete: boolean;
}

/** Preserve the durable profile after an independent extension assignment
 * failure. A retry updates that same profile with any later form edits before
 * assigning extensions, so creation is never repeated and edits are not lost. */
export async function persistProfileWithExtensions<TProfile extends IdentifiedProfile>({
  savedProfile,
  extensionIds,
  saveProfile,
  updateSavedProfile,
  assignExtensions,
}: PersistProfileWithExtensionsInput<TProfile>): Promise<ProfilePersistenceResult<TProfile>> {
  const profile = savedProfile ? await updateSavedProfile(savedProfile) : await saveProfile();
  if (extensionIds.length === 0) return { profile, assignmentComplete: true };
  try {
    await assignExtensions(profile.id, extensionIds);
    return { profile, assignmentComplete: true };
  } catch {
    return { profile, assignmentComplete: false };
  }
}
