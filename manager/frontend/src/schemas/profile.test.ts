import { describe, expect, it, vi } from 'vitest';
import { profiles } from '@/mocks/data';
import {
  defaultWizardValues,
  profileToWizardValues,
  profileWizardSchema,
  randomSeed,
  wizardValuesToPatch,
  wizardValuesToPayload,
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

describe('explicit fingerprint attributes', () => {
  it('keeps every override automatic by default and serializes it as null', () => {
    const values = defaultWizardValues();

    expect(values).toMatchObject({
      gpu_vendor: '',
      gpu_renderer: '',
      hardware_concurrency: '',
      device_memory: '',
      screen_width: '',
      screen_height: '',
      brand: '',
    });
    expect(wizardValuesToPayload(values)).toMatchObject({
      gpu_vendor: null,
      gpu_renderer: null,
      hardware_concurrency: null,
      device_memory: null,
      screen_width: null,
      screen_height: null,
      brand: null,
    });
  });

  it('trims strings and serializes explicit numeric controls as integers', () => {
    const payload = wizardValuesToPayload(
      defaultWizardValues({
        gpu_vendor: '  Neutral Graphics  ',
        gpu_renderer: '  ANGLE (Neutral Graphics, Model 800, Direct3D11)  ',
        hardware_concurrency: '12',
        device_memory: '16',
        screen_width: '1920',
        screen_height: '1080',
        brand: '  BrowserCo  ',
      }),
    );

    expect(payload).toMatchObject({
      gpu_vendor: 'Neutral Graphics',
      gpu_renderer: 'ANGLE (Neutral Graphics, Model 800, Direct3D11)',
      hardware_concurrency: 12,
      device_memory: 16,
      screen_width: 1920,
      screen_height: 1080,
      brand: 'BrowserCo',
    });
  });

  it('rejects a screen override unless width and height are supplied together', () => {
    const onlyWidth = profileWizardSchema.safeParse(
      defaultWizardValues({ screen_width: '1920', screen_height: '' }),
    );
    const onlyHeight = profileWizardSchema.safeParse(
      defaultWizardValues({ screen_width: '', screen_height: '1080' }),
    );

    expect(onlyWidth.success).toBe(false);
    expect(onlyHeight.success).toBe(false);
  });

  it('hydrates all explicit overrides when editing an existing profile', () => {
    const loaded = {
      ...profiles[0],
      gpu_vendor: 'Neutral Graphics',
      gpu_renderer: 'ANGLE (Neutral Graphics, Model 800, Direct3D11)',
      hardware_concurrency: 12,
      device_memory: 16,
      screen_width: 1920,
      screen_height: 1080,
      brand: 'BrowserCo',
    };

    expect(profileToWizardValues(loaded)).toMatchObject({
      gpu_vendor: 'Neutral Graphics',
      gpu_renderer: 'ANGLE (Neutral Graphics, Model 800, Direct3D11)',
      hardware_concurrency: '12',
      device_memory: '16',
      screen_width: '1920',
      screen_height: '1080',
      brand: 'BrowserCo',
    });
  });
});
