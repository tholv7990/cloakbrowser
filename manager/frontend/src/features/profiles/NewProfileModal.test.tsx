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

beforeEach(() => mockStore.reset());

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
    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 2));
    expect(mockStore.proxies.length).toBe(proxiesBefore + 2);
  });

  it('creates a numbered batch when count > 1', async () => {
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Batch');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '3' } });
    await user.click(screen.getByRole('button', { name: /create all/i }));

    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 3));
    const names = mockStore.profiles.map((p) => p.name);
    expect(names).toContain('Batch 01');
    expect(names).toContain('Batch 03');
  });
});
