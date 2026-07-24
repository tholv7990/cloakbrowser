import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { mockStore } from '@/mocks/store';
import { renderWithProviders } from '@/test/utils';
import { LicenseSection } from './LicenseSection';

describe('LicenseSection', () => {
  beforeEach(() => mockStore.reset());

  it('shows the disabled state and no actions when signed out', async () => {
    renderWithProviders(<LicenseSection />);

    expect(await screen.findByText('Enforcement off')).toBeInTheDocument();
    expect(screen.getByText('Not signed in')).toBeInTheDocument();
    expect(screen.queryByText('Refresh license')).not.toBeInTheDocument();
  });

  it('shows plan, email, and actions when signed in and licensed', async () => {
    mockStore.license = {
      state: 'active',
      allowed: true,
      plan: 'pro',
      features: [],
      expires_at: 1_800_000_000,
      grace_deadline: null,
      detail: null,
    };
    mockStore.account = { cloud_configured: true, signed_in: true, email: 'a@b.co' };
    renderWithProviders(<LicenseSection />);

    expect(await screen.findByText('Active')).toBeInTheDocument();
    expect(screen.getByText('pro')).toBeInTheDocument();
    expect(screen.getByText('Signed in as a@b.co')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Sign out'));
    expect(await screen.findByText('Not signed in')).toBeInTheDocument();
  });
});
