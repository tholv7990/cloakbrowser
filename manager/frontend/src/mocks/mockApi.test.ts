import { beforeEach, describe, expect, it } from 'vitest';
import { mockApi } from './mockApi';
import { mockStore } from './store';
import { ApiError } from '@/api/http';
import { emptyProfileWrite, readToWrite } from '@/features/profiles/view';

beforeEach(() => mockStore.reset());

describe('mock profiles contract', () => {
  it('paginates and reports totals with the `pages` field', async () => {
    const page1 = await mockApi.listProfiles({ page: 1, page_size: 10, sort: 'name' });
    expect(page1.items).toHaveLength(10);
    expect(page1.total).toBeGreaterThan(10);
    expect(page1.pages).toBe(Math.ceil(page1.total / 10));

    const page2 = await mockApi.listProfiles({ page: 2, page_size: 10, sort: 'name' });
    expect(page2.items[0].id).not.toBe(page1.items[0].id);
  });

  it('returns normalized profiles (tag_ids, workflow_status_id, runtime_state)', async () => {
    const { items } = await mockApi.listProfiles({ page: 1, page_size: 1 });
    const profile = items[0];
    expect(Array.isArray(profile.tag_ids)).toBe(true);
    expect(profile).toHaveProperty('runtime_state');
    expect(profile).toHaveProperty('location');
    expect(profile).not.toHaveProperty('windows_persona');
  });

  it('filters by search query', async () => {
    const byName = await mockApi.listProfiles({ query: 'capgridshop', page: 1, page_size: 25 });
    expect(byName.total).toBeGreaterThan(0);
    expect(
      byName.items.every((p) => p.name.includes('capgridshop') || p.notes.includes('capgridshop')),
    ).toBe(true);
  });

  it('filters pinned profiles', async () => {
    const pinned = await mockApi.listProfiles({ pinned: true, page: 1, page_size: 50 });
    expect(pinned.items.length).toBeGreaterThan(0);
    expect(pinned.items.every((p) => p.pinned)).toBe(true);
  });

  it('creates a stopped profile from a full ProfileWrite and lists it', async () => {
    const before = await mockApi.listProfiles({ page: 1, page_size: 100 });
    const created = await mockApi.createProfile(emptyProfileWrite('test-created'));
    expect(created.runtime_state).toBe('stopped');
    expect(created.fingerprint_revision).toBe(1);
    const after = await mockApi.listProfiles({ page: 1, page_size: 100 });
    expect(after.total).toBe(before.total + 1);
  });

  it('rejects a second start of the same profile', async () => {
    const stopped = await mockApi.listProfiles({ page: 1, page_size: 100 });
    const id = stopped.items.find((p) => p.runtime_state === 'stopped')!.id;
    const started = await mockApi.startProfile(id);
    expect(started.runtime_state).toBe('starting');
    await expect(mockApi.startProfile(id)).rejects.toMatchObject({
      code: 'profile_already_running',
    });
  });

  it('applies bulk actions with the new action names', async () => {
    const { items } = await mockApi.listProfiles({ page: 1, page_size: 3 });
    const ids = items.map((p) => p.id);
    const result = await mockApi.bulkProfiles({ action: 'pin', ids });
    expect(result.count).toBe(ids.length);
    expect(result.updated_ids).toEqual(ids);
    const pinned = await mockApi.listProfiles({ pinned: true, page: 1, page_size: 100 });
    expect(ids.every((id) => pinned.items.some((p) => p.id === id))).toBe(true);
  });

  it('inline-edits a single field via a full-object PATCH (name + tags)', async () => {
    const { items } = await mockApi.listProfiles({ page: 1, page_size: 1 });
    const read = await mockApi.getProfile(items[0].id);
    const updated = await mockApi.updateProfile(read.id, {
      ...readToWrite(read),
      name: 'renamed-inline',
      tag_ids: ['tag-us'],
    });
    expect(updated.name).toBe('renamed-inline');
    expect(updated.tag_ids).toEqual(['tag-us']);
    // Unchanged grouped settings survive the full-object replace.
    expect(updated.location).toEqual(read.location);
  });
});

describe('mock settings contract', () => {
  it('checks for a browser update and returns refreshed binary facts', async () => {
    const settings = await mockApi.checkBrowserUpdate();
    expect(settings.browser.version).toBeTruthy();
    expect(settings.browser.tier).toBe('free');
    expect(settings.license.configured).toBe(false);
  });
});

describe('mock catalog: tag create-and-apply', () => {
  it('creates a tag and dedupes by name', async () => {
    const before = await mockApi.listTags();
    const created = await mockApi.createTag({ name: 'fresh-tag', color: '#2F6FEB' });
    expect(created.id).toBeTruthy();
    expect(created.name).toBe('fresh-tag');
    const after = await mockApi.listTags();
    expect(after).toHaveLength(before.length + 1);
    const dup = await mockApi.createTag({ name: 'fresh-tag' });
    expect(dup.id).toBe(created.id);
    expect(await mockApi.listTags()).toHaveLength(before.length + 1);
  });
});

describe('mock auth contract', () => {
  it('reports setup not required and issues a session with a CSRF token', async () => {
    const status = await mockApi.authStatus();
    expect(status.setup_required).toBe(false);
    const session = await mockApi.authLogin({
      email: 'owner@localhost',
      password: 'a-very-long-password',
    });
    expect(session.email).toBe('owner@localhost');
    expect(session.csrf_token).toBeTruthy();
  });

  it('starts logged out, authenticates on login, and fails the session after logout', async () => {
    // Mock starts signed out so the login page is the entry point.
    await expect(mockApi.authSession()).rejects.toMatchObject({ status: 401 });
    await mockApi.authLogin({ email: 'owner@localhost', password: 'a-very-long-password' });
    await expect(mockApi.authSession()).resolves.toBeTruthy();
    await mockApi.authLogout();
    await expect(mockApi.authSession()).rejects.toMatchObject({ status: 401 });
  });
});

describe('mock proxy contract (secret safety)', () => {
  it('never exposes a raw password on any proxy response', async () => {
    const proxies = await mockApi.listProxies();
    for (const proxy of proxies) {
      expect(proxy).not.toHaveProperty('password');
      expect(typeof proxy.has_password).toBe('boolean');
    }
  });

  it('parses common proxy formats without echoing the password', async () => {
    const a = await mockApi.parseProxy('socks5h://user:secret@host.example:1080');
    expect(a).toMatchObject({
      scheme: 'socks5h',
      host: 'host.example',
      port: 1080,
      username: 'user',
      has_password: true,
    });
    expect(a).not.toHaveProperty('password');

    const b = await mockApi.parseProxy('1.2.3.4:8080:user:pw');
    expect(b).toMatchObject({ host: '1.2.3.4', port: 8080, username: 'user', has_password: true });

    const c = await mockApi.parseProxy('proxy.example:3128');
    expect(c).toMatchObject({ host: 'proxy.example', port: 3128, has_password: false });
  });

  it('keeps the stored password when an update sends a blank one', async () => {
    const [proxy] = await mockApi.listProxies();
    const withPassword = proxy.has_password;
    const updated = await mockApi.updateProxy(proxy.id, {
      label: proxy.label,
      scheme: proxy.scheme,
      host: proxy.host,
      port: proxy.port,
      username: proxy.username,
      password: undefined,
      test_before_launch: proxy.test_before_launch,
    });
    expect(updated.has_password).toBe(withPassword);
  });

  it('refuses to delete a proxy that is still assigned', async () => {
    const proxies = await mockApi.listProxies();
    const assigned = proxies.find((p) => p.assigned_profile_count > 0)!;
    await expect(mockApi.deleteProxy(assigned.id)).rejects.toBeInstanceOf(ApiError);
  });
});
