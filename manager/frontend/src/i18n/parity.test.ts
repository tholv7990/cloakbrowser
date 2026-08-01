import { describe, expect, it } from 'vitest';
import { en } from './en';
import { vi } from './vi';

const findingKeys = [
  'editor.finding.ua.platformMismatch',
  'editor.finding.ua.versionMismatch',
  'editor.finding.gpu.vendorRendererMismatch',
  'editor.finding.gpu.platformMismatch',
  'editor.finding.geo.timezoneMismatch',
  'editor.finding.geo.localeMismatch',
] as const;

describe('English and Vietnamese translation parity', () => {
  it('keeps the dictionaries synchronized', () => {
    expect(Object.keys(vi).sort()).toEqual(Object.keys(en).sort());
  });

  it.each(findingKeys)('defines localized copy for backend finding %s', (key) => {
    expect(en[key]).toBeTruthy();
    expect(vi[key]).toBeTruthy();
    expect(vi[key]).not.toBe(en[key]);
  });
});
