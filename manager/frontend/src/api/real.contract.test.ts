import { beforeEach, describe, expect, it, vi } from 'vitest';
import { realApi } from './real';

const jsonResponse = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

const proxyResponse = {
  id: 'proxy-1',
  label: 'Strict proxy',
  scheme: 'socks5',
  host: 'proxy.example',
  port: 1080,
  username: 'proxy-user',
  has_password: true,
  masked_endpoint: 'socks5://proxy.example:1080',
  test_before_launch: true,
  assigned_profile_count: 0,
  exit_ip: null,
  country: null,
  city: null,
  timezone: null,
  asn: null,
  organization: null,
  proxy_type: null,
  type_confidence: null,
  reputation: null,
  latency_ms: null,
  last_checked_at: null,
  created_at: '2026-08-02T00:00:00Z',
  updated_at: '2026-08-02T00:00:00Z',
};

describe('real Manager adapter contract', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('sends a conflict-safe partial profile patch without full-object defaults', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ id: 'p-1' }));

    await realApi.updateProfile('p-1', {
      expected_updated_at: '2026-07-22T00:00:00Z',
      notes: 'changed',
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe('PATCH');
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_updated_at: '2026-07-22T00:00:00Z',
      notes: 'changed',
    });
  });

  it('posts a fingerprint draft to the canonical validation endpoint', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(jsonResponse({ status: 'coherent', findings: [] }));
    const draft = {
      browser_version_mode: 'installed' as const,
      browser_version: null,
      user_agent_mode: 'automatic' as const,
      custom_user_agent: null,
      location: {
        geo_mode: 'proxy' as const,
        locale: 'en-US',
        timezone: 'America/New_York',
        webrtc_mode: 'proxy' as const,
        geolocation_mode: 'ask' as const,
        latitude: null,
        longitude: null,
        accuracy: null,
      },
      proxy_id: null,
      gpu_vendor: 'Neutral Graphics',
      gpu_renderer: null,
      hardware_concurrency: null,
      device_memory: null,
      screen_width: null,
      screen_height: null,
      brand: null,
    };

    await realApi.validateProfileDraft(draft);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/profiles/validate');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual(draft);
  });

  it('rejects leaked password fields from every live proxy response call', async () => {
    const leaked = { ...proxyResponse, password: 'must-never-reach-the-ui' };
    const payload = {
      label: 'Strict proxy',
      scheme: 'socks5' as const,
      host: 'proxy.example',
      port: 1080,
      username: 'proxy-user',
      password: 'write-only',
      test_before_launch: true,
    };
    const calls = [
      { response: [leaked], invoke: () => realApi.listProxies() },
      { response: leaked, invoke: () => realApi.getProxy('proxy-1') },
      { response: leaked, invoke: () => realApi.createProxy(payload) },
      { response: leaked, invoke: () => realApi.updateProxy('proxy-1', payload) },
    ];

    for (const call of calls) {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse(call.response));
      await expect(call.invoke()).rejects.toThrow();
      vi.restoreAllMocks();
    }
  });

  it('maps paginated logs, extension operations, and diagnostics filters to canonical routes', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() =>
        Promise.resolve(jsonResponse({ items: [], total: 0, page: 1, page_size: 50, pages: 0 })),
      );

    await realApi.getProfileLogs('p-1', { page: 2, page_size: 100 });
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain(
      '/profiles/p-1/logs?page=2&page_size=100',
    );

    await realApi.registerExtension('C:\\extensions\\safe');
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({
      directory: 'C:\\extensions\\safe',
    });

    await realApi.setProfileExtensions('p-1', ['00000000-0000-4000-8000-000000000001']);
    expect(fetchMock.mock.calls.at(-1)?.[1]?.method).toBe('PUT');

    await realApi.getProfileExtensions('p-1');
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('/profiles/p-1/extensions');
    expect(fetchMock.mock.calls.at(-1)?.[1]?.method).toBe('GET');

    await realApi.getProfileLogTail('p-1', { cursor: 'opaque-cursor', limit: 25 });
    const tailUrl = String(fetchMock.mock.calls.at(-1)?.[0]);
    expect(tailUrl).toContain('/profiles/p-1/logs/tail?');
    expect(tailUrl).toContain('cursor=opaque-cursor');
    expect(tailUrl).toContain('limit=25');

    await realApi.listDiagnostics({ kind: 'pixelscan', status: 'warning', page: 3 });
    const diagnosticUrl = String(fetchMock.mock.calls.at(-1)?.[0]);
    expect(diagnosticUrl).toContain('/diagnostics?');
    expect(diagnosticUrl).toContain('kind=pixelscan');
    expect(diagnosticUrl).toContain('status=warning');
    expect(diagnosticUrl).toContain('page=3');

    await realApi.runDiagnostic('cloudflare', 'p-1');
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('/diagnostics/cloudflare');
    expect(JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body))).toEqual({
      profile_id: 'p-1',
    });

    await realApi.runDiagnostic('google_search', 'p-1');
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('/diagnostics/google-search');
  });

  it('preserves server filenames for profile and cookie downloads', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response('{"format":"cloakbrowser-manager-profile"}', {
          headers: {
            'Content-Type': 'application/json',
            'Content-Disposition': 'attachment; filename="cloakbrowser-profile-safe.json"',
          },
        }),
      )
      .mockResolvedValueOnce(
        new Response('# Netscape HTTP Cookie File\n', {
          headers: {
            'Content-Type': 'text/plain',
            'Content-Disposition': 'attachment; filename="cloakbrowser-cookies-safe.txt"',
          },
        }),
      );

    await expect(realApi.exportProfile('p-1')).resolves.toMatchObject({
      filename: 'cloakbrowser-profile-safe.json',
    });
    await expect(realApi.exportCookies('p-1', 'netscape')).resolves.toMatchObject({
      filename: 'cloakbrowser-cookies-safe.txt',
    });
  });
});
