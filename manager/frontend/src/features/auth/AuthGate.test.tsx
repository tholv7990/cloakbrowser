import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { AuthScreen } from './AuthGate';

function renderScreen(initialMode: 'setup' | 'login') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AuthScreen initialMode={initialMode} />
    </QueryClientProvider>,
  );
}

describe('AuthScreen sign in / create-account switch', () => {
  it('toggles between the two modes via the switch link', async () => {
    renderScreen('login');

    // Login mode: Sign-in heading, no confirm-password field.
    expect(screen.getByRole('heading', { name: /^sign in$/i })).toBeInTheDocument();
    expect(screen.queryByText('Confirm password')).not.toBeInTheDocument();

    // Switch to create-account.
    await userEvent.click(screen.getByRole('button', { name: /need an account/i }));
    expect(
      screen.getByRole('heading', { name: /create your owner account/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('Confirm password')).toBeInTheDocument();

    // Switch back to sign-in.
    await userEvent.click(screen.getByRole('button', { name: /already have an account/i }));
    expect(screen.getByRole('heading', { name: /^sign in$/i })).toBeInTheDocument();
    expect(screen.queryByText('Confirm password')).not.toBeInTheDocument();
  });
});
