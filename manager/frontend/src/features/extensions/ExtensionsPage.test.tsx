import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { mockApi } from '@/mocks/mockApi';
import { ExtensionsPage } from './ExtensionsPage';

describe('ExtensionsPage', () => {
  beforeEach(() => mockStore.reset());

  it('lists registered unpacked extensions and warns about correlation', async () => {
    renderWithProviders(<ExtensionsPage />);
    expect(await screen.findByText('Wallet helper (local)')).toBeInTheDocument();
    expect(screen.getByText(/uncommon extensions can link/i)).toBeInTheDocument();
  });

  it('registers a local directory through the catalog API', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ExtensionsPage />);
    await user.click(await screen.findByRole('button', { name: /register extension/i }));
    await user.type(screen.getByLabelText(/extension directory/i), 'C:\\extensions\\new-one');
    await user.click(screen.getByRole('button', { name: /^register$/i }));
    expect(await screen.findByText('new-one')).toBeInTheDocument();
  });

  it('shows a failed mutation and lets the owner retry it', async () => {
    const user = userEvent.setup();
    const original = mockApi.updateExtension.bind(mockApi);
    const update = vi
      .spyOn(mockApi, 'updateExtension')
      .mockRejectedValueOnce(new Error('extension refresh failed'))
      .mockImplementation(original);
    renderWithProviders(<ExtensionsPage />);

    await user.click((await screen.findAllByRole('button', { name: /disable/i }))[0]);
    expect(await screen.findByRole('alert')).toHaveTextContent('extension refresh failed');
    await user.click(screen.getByRole('button', { name: /retry extension action/i }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
  });

  it('keeps unregister failure and retry visible inside the confirmation dialog', async () => {
    const user = userEvent.setup();
    const original = mockApi.unregisterExtension.bind(mockApi);
    const unregister = vi
      .spyOn(mockApi, 'unregisterExtension')
      .mockRejectedValueOnce(new Error('extension unregister failed'))
      .mockImplementation(original);
    renderWithProviders(<ExtensionsPage />);

    await user.click((await screen.findAllByRole('button', { name: /^unregister$/i }))[0]);
    const dialog = await screen.findByRole('dialog', { name: /unregister extension/i });
    await user.click(within(dialog).getByRole('button', { name: /^unregister$/i }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'extension unregister failed',
    );
    await user.click(within(dialog).getByRole('button', { name: /retry extension action/i }));
    await waitFor(() => expect(unregister).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
