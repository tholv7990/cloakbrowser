import { beforeEach, describe, expect, it } from 'vitest';
import { mockApi } from './mockApi';
import { mockStore } from './store';
import { ApiError } from '@/api/http';
import { emptyProfileWrite } from '@/features/profiles/view';

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
    await mockApi.startProfile(id);
    expect((await mockApi.getProfile(id)).runtime_state).toBe('starting');
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

  it('inline-edits fields via a conflict-safe partial PATCH', async () => {
    const { items } = await mockApi.listProfiles({ page: 1, page_size: 1 });
    const read = await mockApi.getProfile(items[0].id);
    const updated = await mockApi.updateProfile(read.id, {
      expected_updated_at: read.updated_at,
      name: 'renamed-inline',
      tag_ids: ['tag-us'],
    });
    expect(updated.name).toBe('renamed-inline');
    expect(updated.tag_ids).toEqual(['tag-us']);
    // Unchanged grouped settings survive because omitted fields are untouched.
    expect(updated.location).toEqual(read.location);
  });
});

describe('mock portability and UUID parity', () => {
  const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  it('rejects a profile document without the canonical format and version', async () => {
    await expect(
      mockApi.importProfile({ schema_version: 1, profile: { name: 'wrong' } }),
    ).rejects.toMatchObject({
      status: 422,
      code: 'profile_import_invalid',
    });
  });

  it('uses canonical UUIDs for newly registered extensions', async () => {
    const extension = await mockApi.registerExtension('C:\\extensions\\uuid');
    expect(extension.id).toMatch(UUID_V4);
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

describe('mock automation contract', () => {
  it('records a flow into a template with derived variables', async () => {
    const profile = (await mockApi.listProfiles({ page: 1, page_size: 1, sort: 'name' })).items[0];
    const rec = await mockApi.startRecording({
      name: 'Signup',
      profile_id: profile.id,
      description: '',
    });
    expect(rec.status).toBe('recording');
    const tpl = await mockApi.stopRecording(rec.id);
    expect(tpl.steps.length).toBeGreaterThanOrEqual(3);
    expect(tpl.variables).toContain('email');
    expect((await mockApi.getRecording(rec.id)).template_id).toBe(tpl.id);
  });

  it('starts a run with one pending item per assignment and honors run actions', async () => {
    const templates = await mockApi.listTemplates();
    const profiles = (await mockApi.listProfiles({ page: 1, page_size: 2, sort: 'name' })).items;
    const run = await mockApi.startRun(templates[0].id, {
      assignments: profiles.map((p) => ({
        profile_id: p.id,
        variables: {},
        credential_id: 'pool',
      })),
      max_parallel: 2,
    });
    expect(run.total).toBe(2);
    expect(run.items.every((i) => i.status === 'pending')).toBe(true);

    const done = await mockApi.markRunProfileCompleted(run.id, profiles[0].id);
    expect(done.items.find((i) => i.profile_id === profiles[0].id)!.status).toBe('completed');
    expect(done.completed_count).toBe(1);

    const cancelled = await mockApi.cancelRun(run.id);
    expect(cancelled.status).toBe('cancelled');
  });

  it('imports credentials as counts only (no secrets returned)', async () => {
    const before = await mockApi.getCredentialPool();
    const after = await mockApi.importCredentials('a@x.com:pw1\nb@x.com:pw2\nnot-a-credential');
    expect(after.available).toBe(before.available + 2);
    expect(JSON.stringify(after)).not.toContain('pw1');
  });
});

describe('mock shopify builder contract', () => {
  it('connects a store without echoing the client secret', async () => {
    const store = await mockApi.connectStore({
      label: 'My store',
      shop_domain: 'my-shop.myshopify.com',
      client_id: 'abc',
      client_secret: 'super-secret',
      proxy_id: null,
    });
    expect(store.connected).toBe(true);
    expect(Object.keys(store.capabilities)).toContain('write_products');
    expect(JSON.stringify(store)).not.toContain('super-secret');
  });

  it('stages a draft-only plan and requires confirmation to execute', async () => {
    const store = await mockApi.connectStore({
      label: 'Plan store',
      shop_domain: 'plan-shop.myshopify.com',
      client_id: 'abc',
      client_secret: 'x',
      proxy_id: null,
    });
    const plan = await mockApi.createBuildPlan(store.id, {
      theme_id: 'thm_dawn',
      preset: 'Default',
      product_source: 'catalog',
      catalog_id: 'cat_vst',
      ai_hero: false,
    });
    expect(plan.status).toBe('staged');
    expect(plan.mode).toBe('draft_only');
    expect(plan.steps).toHaveLength(9);
    expect(plan.admin_url).toBeNull();

    await expect(mockApi.executeBuildPlan(store.id, plan.id, false)).rejects.toBeInstanceOf(
      ApiError,
    );
    const running = await mockApi.executeBuildPlan(store.id, plan.id, true);
    expect(running.status).toBe('running');
  });
});

describe('mock runtime extras contract', () => {
  it('lists per-launch session history', async () => {
    const sessions = await mockApi.listSessions(5);
    expect(sessions.length).toBeGreaterThan(0);
    expect(sessions[0]).toHaveProperty('startup_ms');
    expect(sessions[0]).toHaveProperty('exit_reason');
  });

  it('creates and deletes backups; restore of a missing id fails', async () => {
    const before = (await mockApi.listBackups()).length;
    const created = await mockApi.createBackup();
    expect((await mockApi.listBackups()).length).toBe(before + 1);
    expect(created.verified).toBe(true);
    await expect(mockApi.restoreBackup('bkp_missing')).rejects.toBeInstanceOf(ApiError);
    await mockApi.deleteBackup(created.id);
    expect((await mockApi.listBackups()).length).toBe(before);
  });

  it('adds and removes media assets and toggles injection', async () => {
    const before = (await mockApi.listMediaAssets()).length;
    const asset = await mockApi.createMediaAsset({
      name: 'Test cam',
      kind: 'camera',
      format: 'video/mp4',
    });
    expect((await mockApi.listMediaAssets()).length).toBe(before + 1);
    const settings = await mockApi.updateMediaSettings({ enabled: true });
    expect(settings.enabled).toBe(true);
    await mockApi.deleteMediaAsset(asset.id);
    expect((await mockApi.listMediaAssets()).length).toBe(before);
  });
});
