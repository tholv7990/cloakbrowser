import { describe, expect, it } from 'vitest';
import { proxyFormSchema, toProxyPayload } from './proxy';

describe('proxyFormSchema', () => {
  it('requires host and port for non-direct schemes', () => {
    const result = proxyFormSchema.safeParse({
      label: 'x',
      scheme: 'http',
      host: '',
      port: '',
      username: '',
      test_before_launch: false,
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths).toContain('host');
      expect(paths).toContain('port');
    }
  });

  it('allows a direct connection with no host or port', () => {
    const result = proxyFormSchema.safeParse({
      label: 'Direct',
      scheme: 'direct',
      host: '',
      port: '',
      username: '',
      test_before_launch: false,
    });
    expect(result.success).toBe(true);
  });

  it('omits the password from the payload when left blank (write-only)', () => {
    const parsed = proxyFormSchema.parse({
      label: 'x',
      scheme: 'http',
      host: 'h',
      port: 8080,
      username: 'u',
      password: '',
      test_before_launch: true,
    });
    const payload = toProxyPayload(parsed);
    expect(payload.password).toBeUndefined();
  });

  it('includes the password only when the user typed one', () => {
    const parsed = proxyFormSchema.parse({
      label: 'x',
      scheme: 'http',
      host: 'h',
      port: 8080,
      username: 'u',
      password: 'secret',
      test_before_launch: true,
    });
    const payload = toProxyPayload(parsed);
    expect(payload.password).toBe('secret');
  });
});
