import { describe, expect, it } from 'vitest';
import { countryFlag } from './format';

describe('countryFlag', () => {
  it('maps a 2-letter code to the regional-indicator flag emoji', () => {
    expect(countryFlag('US')).toBe('🇺🇸');
    expect(countryFlag('us')).toBe('🇺🇸'); // case-insensitive
    expect(countryFlag('VN')).toBe('🇻🇳');
  });

  it('returns empty for anything that is not a 2-letter code', () => {
    expect(countryFlag(null)).toBe('');
    expect(countryFlag(undefined)).toBe('');
    expect(countryFlag('USA')).toBe('');
    expect(countryFlag('1A')).toBe('');
    expect(countryFlag('')).toBe('');
  });
});
