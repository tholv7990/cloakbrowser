import { describe, expect, it } from 'vitest';
import { profiles } from '@/mocks/data';
import { profileToWizardValues, wizardValuesToPatch } from './profile';

describe('wizardValuesToPatch', () => {
  it('hydrates existing extension assignments into the editor values', () => {
    const loaded = profiles[0];
    const extensionIds = [
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
    ];

    expect(profileToWizardValues(loaded, extensionIds).extension_ids).toEqual(extensionIds);
  });

  it('omits unchanged fields and preserves pinned state from the loaded profile', () => {
    const loaded = { ...profiles.find((profile) => profile.pinned)!, pinned: true };
    const values = profileToWizardValues(loaded);

    expect(wizardValuesToPatch(values, loaded)).toEqual({
      expected_updated_at: loaded.updated_at,
    });
  });

  it('sends only the changed atomic profile field', () => {
    const loaded = profiles[0];
    const values = profileToWizardValues(loaded);
    values.notes = 'reviewed';

    expect(wizardValuesToPatch(values, loaded)).toEqual({
      expected_updated_at: loaded.updated_at,
      notes: 'reviewed',
    });
  });
});
