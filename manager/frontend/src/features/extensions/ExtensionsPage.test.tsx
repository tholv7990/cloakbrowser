import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
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
});
