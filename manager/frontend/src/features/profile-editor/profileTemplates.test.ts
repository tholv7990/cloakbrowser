import { beforeEach, describe, expect, it } from 'vitest';
import { deleteTemplate, listTemplates, saveTemplate } from './profileTemplates';
import type { ProfileWizardValues } from '@/schemas/profile';

const values = { name: 'p1', fingerprint_seed: '42', proxy_id: 'x' } as unknown as ProfileWizardValues;

describe('profileTemplates', () => {
  beforeEach(() => localStorage.clear());

  it('saves, lists and deletes; strips the name from config', () => {
    expect(listTemplates()).toEqual([]);
    const template = saveTemplate('US residential', values);
    expect(template.name).toBe('US residential');
    expect(template.config).not.toHaveProperty('name'); // name stays per-profile
    expect(template.config.fingerprint_seed).toBe('42');
    expect(listTemplates()).toHaveLength(1);

    deleteTemplate(template.id);
    expect(listTemplates()).toEqual([]);
  });

  it('re-saving the same name replaces the template (no duplicates)', () => {
    saveTemplate('US residential', values);
    saveTemplate('US residential', { ...values, proxy_id: 'y' } as ProfileWizardValues);
    const all = listTemplates();
    expect(all).toHaveLength(1);
    expect(all[0].config.proxy_id).toBe('y');
  });
});
