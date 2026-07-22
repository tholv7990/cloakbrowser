import { beforeEach, describe, expect, it, vi } from 'vitest';
import { realApi } from './real';

const jsonResponse = (body: unknown, init: ResponseInit = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

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
