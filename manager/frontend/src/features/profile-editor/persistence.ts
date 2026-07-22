interface PersistProfileWithExtensionsInput {
  savedProfileId: string | null;
  extensionIds: string[];
  saveProfile: () => Promise<{ id: string }>;
  assignExtensions: (profileId: string, extensionIds: string[]) => Promise<unknown>;
}

export interface ProfilePersistenceResult {
  profileId: string;
  assignmentComplete: boolean;
}

/** Preserve the durable profile ID when the independent extension assignment
 * request fails, allowing a retry without repeating profile creation/update. */
export async function persistProfileWithExtensions({
  savedProfileId,
  extensionIds,
  saveProfile,
  assignExtensions,
}: PersistProfileWithExtensionsInput): Promise<ProfilePersistenceResult> {
  const profileId = savedProfileId ?? (await saveProfile()).id;
  if (extensionIds.length === 0) return { profileId, assignmentComplete: true };
  try {
    await assignExtensions(profileId, extensionIds);
    return { profileId, assignmentComplete: true };
  } catch {
    return { profileId, assignmentComplete: false };
  }
}
