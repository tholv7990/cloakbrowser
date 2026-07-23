import { beforeEach, describe, expect, it } from 'vitest';
import { deleteTemplate, isBuiltinTemplate, listTemplates, saveTemplate } from './profileTemplates';
import type { ProfileWizardValues } from '@/schemas/profile';

const values = { name: 'p1', fingerprint_seed: '42', proxy_id: 'x' } as unknown as ProfileWizardValues;
const userOnly = () => listTemplates().filter((t) => !isBuiltinTemplate(t.id));

describe('profileTemplates', () => {
  beforeEach(() => localStorage.clear());

  it('always includes the non-deletable built-in no-leak template', () => {
    expect(listTemplates().some((t) => t.id === 'builtin:no-leak')).toBe(true);
    deleteTemplate('builtin:no-leak'); // no-op — built-ins are permanent
    expect(listTemplates().some((t) => t.id === 'builtin:no-leak')).toBe(true);
  });

  it('saves, lists and deletes user templates; strips the name from config', () => {
    expect(userOnly()).toEqual([]);
    const template = saveTemplate('US residential', values);
    expect(template.name).toBe('US residential');
    expect(template.config).not.toHaveProperty('name'); // name stays per-profile
    expect(template.config.fingerprint_seed).toBe('42');
    expect(userOnly()).toHaveLength(1);

    deleteTemplate(template.id);
    expect(userOnly()).toEqual([]);
  });

  it('re-saving the same name replaces the template (no duplicates)', () => {
    saveTemplate('US residential', values);
    saveTemplate('US residential', { ...values, proxy_id: 'y' } as ProfileWizardValues);
    const all = userOnly();
    expect(all).toHaveLength(1);
    expect(all[0].config.proxy_id).toBe('y');
  });
});
