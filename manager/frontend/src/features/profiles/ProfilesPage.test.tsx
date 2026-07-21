import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { ProfilesPage } from './ProfilesPage';

beforeEach(() => mockStore.reset());

describe('ProfilesPage', () => {
  it('renders profiles from the mock backend with the expected columns', async () => {
    renderWithProviders(<ProfilesPage />);
    expect(await screen.findByText('capgridshop-us-01')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Name/i })).toBeInTheDocument();
    // Masked endpoints only — never a raw credential.
    expect(screen.queryByText(/password/i)).not.toBeInTheDocument();
  });

  it('filters the table via the search box', async () => {
    renderWithProviders(<ProfilesPage />);
    await screen.findByText('capgridshop-us-01');

    // Set the debounced search value in one shot for a deterministic assertion.
    fireEvent.change(screen.getByRole('searchbox', { name: /search profiles/i }), {
      target: { value: 'lacefusion' },
    });

    await waitFor(() => expect(screen.queryByText('capgridshop-us-01')).not.toBeInTheDocument(), {
      timeout: 3000,
    });
    expect(screen.getByText('lacefusion-store')).toBeInTheDocument();
  });

  it('opens the row overflow menu with grouped actions', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfilesPage />);
    await screen.findByText('capgridshop-us-01');

    const [firstActions] = screen.getAllByRole('button', { name: /Actions for/i });
    await user.click(firstActions);
    expect(await screen.findByRole('menuitem', { name: /Edit profile/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Move profile to trash/i })).toBeInTheDocument();
  });
});
