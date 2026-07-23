import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
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
  mockStore.reset();
  localStorage.clear();
});

function templateSelect(): HTMLElement {
  const select = screen
    .getAllByRole('combobox')
    .find((el) => within(el).queryByRole('option', { name: /legacy pinned/i }));
  if (!select) throw new Error('template select not found');
  return select;
}

describe('NewProfileModal', () => {
  it('creates a single named profile', async () => {
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Solo');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 1));
    expect(mockStore.profiles.some((p) => p.name === 'Solo')).toBe(true);
  });

  it('saves a single proxy with the chosen scheme (SOCKS5, not forced http)', async () => {
    const user = userEvent.setup();
    const proxiesBefore = mockStore.proxies.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Sock');
    await user.selectOptions(proxySourceSelect(), 'one');
    // The Type dropdown is the combobox carrying a "SOCKS5" option.
    const typeSelect = screen
      .getAllByRole('combobox')
      .find((el) => within(el).queryByRole('option', { name: /^socks5$/i }));
    if (!typeSelect) throw new Error('proxy type select not found');
    await user.selectOptions(typeSelect, 'socks5');
    // Paste a full proxy string into the paste line; it fills host/port/creds.
    await user.type(screen.getByPlaceholderText('host:port:user:pass'), '1.2.3.4:9000:user:pass');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(mockStore.proxies.length).toBe(proxiesBefore + 1), { timeout: 3000 });
    const created = mockStore.proxies[mockStore.proxies.length - 1];
    expect(created.scheme).toBe('socks5');
    expect(created.host).toBe('1.2.3.4');
    expect(created.port).toBe(9000);
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
});
