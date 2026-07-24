import { describe, expect, it, vi } from 'vitest';
import { profiles } from '@/mocks/data';
import {
  defaultWizardValues,
  profileToWizardValues,
  profileWizardSchema,
  randomSeed,
  wizardValuesToPatch,
} from './profile';

describe('fingerprint seed generation (F-007)', () => {
  it('composes a full 64-bit seed from crypto, not 32-bit Math.random', () => {
    const spy = vi.spyOn(crypto, 'getRandomValues').mockImplementation((array) => {
      const view = array as Uint32Array;
      view[0] = 0xffffffff;
      view[1] = 0x00000002;
      return array;
    });
    try {
      const expected = ((0xffffffffn << 32n) | 0x2n).toString();
      expect(randomSeed()).toBe(expected);
      // The wizard default must use the same strong generator.
      expect(defaultWizardValues().fingerprint_seed).toBe(expected);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('webrtc mode', () => {
  const base = () => profileToWizardValues(profiles[0]);

  it('rejects the retired "disabled" mode (F-001)', () => {
    const values = { ...base(), webrtc_mode: 'disabled' as never };
    expect(profileWizardSchema.safeParse(values).success).toBe(false);
  });

  it('accepts proxy and direct', () => {
    expect(profileWizardSchema.safeParse({ ...base(), webrtc_mode: 'proxy' }).success).toBe(true);
    expect(profileWizardSchema.safeParse({ ...base(), webrtc_mode: 'direct' }).success).toBe(true);
  });
});

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
