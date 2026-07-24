import { describe, expect, it } from 'vitest';
import { parseProxyText, proxyFormSchema, toProxyPayload } from './proxy';

describe('parseProxyText', () => {
  it('parses host:port:user:pass into all four fields incl. password', () => {
    expect(parseProxyText('209.101.202.203:50101:MSproxy:TrustProxy')).toEqual({
      host: '209.101.202.203',
      port: '50101',
      username: 'MSproxy',
      password: 'TrustProxy',
    });
  });

  it('parses scheme://user:pass@host:port with the scheme', () => {
    expect(parseProxyText('socks5h://user:secret@gate.example:1080')).toEqual({
      scheme: 'socks5h',
      host: 'gate.example',
      port: '1080',
      username: 'user',
      password: 'secret',
    });
  });

  it('handles host:port with no credentials, and returns null for incomplete input', () => {
    expect(parseProxyText('1.2.3.4:8080')).toEqual({
      host: '1.2.3.4',
      port: '8080',
      username: '',
      password: '',
    });
    expect(parseProxyText('not-a-proxy')).toBeNull();
    expect(parseProxyText('  ')).toBeNull();
  });
});

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

  it('clears stale credentials when switching an existing proxy to direct', () => {
    // Editing a proxy that HAD a username/password to direct mode: the hidden
    // fields keep their old values, but the backend rejects credentials in
    // direct mode (422). The payload must drop them.
    const parsed = proxyFormSchema.parse({
      label: 'Was a proxy',
      scheme: 'direct',
      host: 'old.host',
      port: 8080,
      username: 'olduser',
      password: 'oldsecret',
      test_before_launch: true,
    });
    const payload = toProxyPayload(parsed);
    expect(payload.host).toBe('');
    expect(payload.port).toBeNull();
    expect(payload.username).toBeNull();
    expect(payload.password).toBeUndefined();
  });
});
