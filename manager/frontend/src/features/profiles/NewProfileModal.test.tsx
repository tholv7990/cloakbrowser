import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { api } from '@/api';
import { mockApi } from '@/mocks/mockApi';
import { mockStore } from '@/mocks/store';
import { NewProfileModal } from './NewProfileModal';

function proxySourceSelect(): HTMLElement {
  // The proxy-source dropdown is the one carrying the "provider" option.
  const select = screen
    .getAllByRole('combobox')
    .find((el) => within(el).queryByRole('option', { name: /generate from a provider/i }));
  if (!select) throw new Error('proxy source select not found');
  return select;
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockStore.reset();
  localStorage.clear();
});

function templateSelect(optionName: RegExp = /legacy pinned/i): HTMLElement {
  const select = screen
    .getAllByRole('combobox')
    .find((el) => within(el).queryByRole('option', { name: optionName }));
  if (!select) throw new Error('template select not found');
  return select;
}

describe('NewProfileModal', () => {
  it('pins the chosen Chromium build on the created profile', async () => {
    const user = userEvent.setup();
    // A newer Pro build is offered alongside the installed one. Capture the real
    // implementation first — in tests `api` IS `mockApi`, so calling it through
    // the spy would recurse.
    const realGetSettings = mockApi.getSettings.bind(mockApi);
    vi.spyOn(api, 'getSettings').mockImplementation(async () => {
      const settings = await realGetSettings();
      return {
        ...settings,
        browser: { ...settings.browser, version: '146.0.7680.177', latest_version: '150.0.1.2' },
      };
    });
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Pinned');
    const versionSelect = await waitFor(() => {
      const select = screen
        .getAllByRole('combobox')
        .find((el) => within(el).queryByRole('option', { name: /latest \(150/i }));
      if (!select) throw new Error('version select not found');
      return select;
    });
    // Defaults to the installed build (no seat limit) until you opt in.
    expect((versionSelect as HTMLSelectElement).value).toBe('');

    await user.selectOptions(versionSelect, '150.0.1.2');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => {
      const created = mockStore.profiles.find((p) => p.name === 'Pinned');
      expect(created?.browser_version_mode).toBe('pinned');
      expect(created?.browser_version).toBe('150.0.1.2');
    });
  });

  it('creates a single named profile', async () => {
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Solo');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 1));
    expect(mockStore.profiles.some((p) => p.name === 'Solo')).toBe(true);
  });

  it('creates a proxy in the drawer and assigns it to the new profile', async () => {
    const user = userEvent.setup();
    const proxiesBefore = mockStore.proxies.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Sock');
    await user.selectOptions(proxySourceSelect(), 'one');
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'socks5://user:pass@1.2.3.4:9000',
    );
    await user.click(screen.getByRole('button', { name: /create proxy/i }));

    await waitFor(() => expect(mockStore.proxies.length).toBe(proxiesBefore + 1));
    const createdProxy = mockStore.proxies[mockStore.proxies.length - 1];
    const validateDraft = vi.spyOn(api, 'validateProfileDraft');
    await user.click(
      within(screen.getByRole('dialog', { name: /edit proxy/i })).getAllByRole('button', {
        name: /close/i,
      })[0],
    );
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() =>
      expect(validateDraft).toHaveBeenCalledWith(
        expect.objectContaining({ proxy_id: createdProxy.id }),
      ),
    );
    await waitFor(() => {
      const createdProfile = mockStore.profiles.find((profile) => profile.name === 'Sock');
      expect(createdProfile?.proxy_id).toBe(createdProxy.id);
    });
    expect(createdProxy.scheme).toBe('socks5');
    expect(createdProxy.host).toBe('1.2.3.4');
    expect(createdProxy.port).toBe(9000);
  });

  it('removes only the proxy assignment and keeps the reusable proxy', async () => {
    const user = userEvent.setup();
    const deleteProxy = vi.spyOn(api, 'deleteProxy');
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Direct after remove');
    await user.selectOptions(proxySourceSelect(), 'one');
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    await user.type(
      await screen.findByPlaceholderText(/socks5h:\/\//i),
      'http://user:pass@198.51.100.42:8080',
    );
    await user.click(screen.getByRole('button', { name: /create proxy/i }));

    await user.click(
      within(await screen.findByRole('dialog', { name: /edit proxy/i })).getAllByRole('button', {
        name: /close/i,
      })[0],
    );
    await waitFor(() => expect(screen.getByRole('button', { name: /^remove$/i })).toBeEnabled());
    const savedProxy = mockStore.proxies[mockStore.proxies.length - 1];
    await user.click(screen.getByRole('button', { name: /^remove$/i }));
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => {
      const createdProfile = mockStore.profiles.find(
        (profile) => profile.name === 'Direct after remove',
      );
      expect(createdProfile?.proxy_id).toBeNull();
    });
    expect(mockStore.proxies.some((proxy) => proxy.id === savedProxy.id)).toBe(true);
    expect(deleteProxy).not.toHaveBeenCalled();
  });

  it('generates provider proxies and assigns one per profile', async () => {
    await mockApi.configureProxyProvider({ provider: 'iproyal', api_token: 'tok' });
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    const proxiesBefore = mockStore.proxies.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Farm');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '2' } });
    await user.selectOptions(proxySourceSelect(), 'provider');
    await user.click(screen.getByRole('button', { name: /create all/i }));

    // 2 profiles created, and 2 provider proxies generated for them.
    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 2), { timeout: 3000 });
    expect(mockStore.proxies.length).toBe(proxiesBefore + 2);
  });

  it('gives every profile a unique fingerprint seed, even from a seed-pinned template', async () => {
    // A legacy template that captured a fingerprint seed must NOT clone it.
    localStorage.setItem(
      'cb.profileTemplates',
      JSON.stringify([
        { id: 'legacy', name: 'Legacy pinned', createdAt: 1, config: { fingerprint_seed: '99999' } },
      ]),
    );
    const user = userEvent.setup();
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Pin');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '5' } });
    await user.selectOptions(templateSelect(), 'legacy');
    await user.click(screen.getByRole('button', { name: /create all/i }));

    await waitFor(
      () => expect(mockStore.profiles.filter((p) => p.name.startsWith('Pin ')).length).toBe(5),
      { timeout: 4000 },
    );
    const seeds = mockStore.profiles
      .filter((p) => p.name.startsWith('Pin '))
      .map((p) => p.fingerprint_seed);
    expect(new Set(seeds).size).toBe(5); // all distinct
    expect(seeds).not.toContain('99999'); // never the pinned seed
  });

  it('creates a numbered batch when count > 1', async () => {
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Batch');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '3' } });
    await user.click(screen.getByRole('button', { name: /create all/i }));

    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 3), { timeout: 3000 });
    const names = mockStore.profiles.map((p) => p.name);
    expect(names).toContain('Batch 01');
    expect(names).toContain('Batch 03');
  });

  it('validates an incoherent template and does not create the profile', async () => {
    localStorage.setItem(
      'cb.profileTemplates',
      JSON.stringify([
        {
          id: 'incoherent',
          name: 'Incoherent identity',
          createdAt: 1,
          config: {
            gpu_vendor: 'Neutral Graphics',
            gpu_renderer: 'ANGLE (Neutral Graphics, Model 800, Metal)',
          },
        },
      ]),
    );
    vi.spyOn(api, 'validateProfileDraft').mockResolvedValue({
      status: 'error',
      findings: [
        {
          code: 'gpu.platform_mismatch',
          severity: 'error',
          field: 'gpu_renderer',
          message: 'Server text is not rendered.',
        },
      ],
    });
    const createProfile = vi.spyOn(api, 'createProfile');
    const user = userEvent.setup();
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Guarded quick create');
    await user.selectOptions(templateSelect(/incoherent identity/i), 'incoherent');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(api.validateProfileDraft).toHaveBeenCalled());
    expect(createProfile).not.toHaveBeenCalled();
    expect(await screen.findByText('Resolve the fingerprint errors before creating profiles.')).toBeInTheDocument();
  });

  it('persists no profiles or proxies when a later batch draft has an error', async () => {
    vi.spyOn(api, 'validateProfileDraft')
      .mockResolvedValueOnce({ status: 'coherent', findings: [] })
      .mockResolvedValueOnce({
        status: 'error',
        findings: [
          {
            code: 'gpu.platform_mismatch',
            severity: 'error',
            field: 'gpu_renderer',
            message: 'Server text is not rendered.',
          },
        ],
      });
    const createProfile = vi.spyOn(api, 'createProfile');
    const createProxy = vi.spyOn(api, 'createProxy');
    const user = userEvent.setup();
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Atomic batch');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '2' } });
    await user.selectOptions(proxySourceSelect(), 'list');
    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), '1.2.3.4:9000:user:pass');
    await user.click(screen.getByRole('button', { name: /create all/i }));

    await waitFor(() => expect(api.validateProfileDraft).toHaveBeenCalledTimes(2));
    expect(createProfile).not.toHaveBeenCalled();
    expect(createProxy).not.toHaveBeenCalled();
  });

  it('persists no profiles or proxies when a later batch validation request fails', async () => {
    vi.spyOn(api, 'validateProfileDraft')
      .mockResolvedValueOnce({
        status: 'warning',
        findings: [
          {
            code: 'geo.timezone_mismatch',
            severity: 'warning',
            field: 'location.timezone',
            message: 'Server text is not rendered.',
          },
        ],
      })
      .mockRejectedValueOnce(new Error('offline'));
    const createProfile = vi.spyOn(api, 'createProfile');
    const createProxy = vi.spyOn(api, 'createProxy');
    const user = userEvent.setup();
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Offline batch');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '2' } });
    await user.selectOptions(proxySourceSelect(), 'list');
    await user.type(screen.getByPlaceholderText(/host:port:user:pass/i), '1.2.3.4:9000:user:pass');
    await user.click(screen.getByRole('button', { name: /create all/i }));

    await waitFor(() => expect(api.validateProfileDraft).toHaveBeenCalledTimes(2));
    expect(createProfile).not.toHaveBeenCalled();
    expect(createProxy).not.toHaveBeenCalled();
  });
});
