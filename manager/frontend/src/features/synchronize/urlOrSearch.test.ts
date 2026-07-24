import { describe, expect, it } from 'vitest';
import { toNavigableUrl } from './urlOrSearch';

describe('toNavigableUrl', () => {
  it('passes through explicit http(s) URLs', () => {
    expect(toNavigableUrl('https://example.com/a?b=1')).toBe('https://example.com/a?b=1');
    expect(toNavigableUrl('  http://example.com  ')).toBe('http://example.com');
  });

  it('treats a bare host as a URL', () => {
    expect(toNavigableUrl('example.com')).toBe('https://example.com');
    expect(toNavigableUrl('example.com/path')).toBe('https://example.com/path');
    expect(toNavigableUrl('localhost:3000')).toBe('https://localhost:3000');
  });

  it('searches anything that is not a URL — what the address bar does', () => {
    expect(toNavigableUrl('best running shoes')).toBe(
      'https://www.google.com/search?q=best%20running%20shoes',
    );
    // A single word is a search, not a host.
    expect(toNavigableUrl('shoes')).toBe('https://www.google.com/search?q=shoes');
  });

  it('refuses schemes that would execute or read locally on every profile', () => {
    expect(toNavigableUrl('javascript:alert(1)')).toBeNull();
    expect(toNavigableUrl('file:///C:/Windows/win.ini')).toBeNull();
    expect(toNavigableUrl('data:text/html,<b>x</b>')).toBeNull();
  });

  it('returns null for empty input', () => {
    expect(toNavigableUrl('   ')).toBeNull();
  });
});
