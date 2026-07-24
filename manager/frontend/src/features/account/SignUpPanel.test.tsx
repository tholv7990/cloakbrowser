import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { SignUpPanel } from './LicenseScreen';
import { api } from '@/api';
import type { LicenseStatus } from '@/types/api';

const LICENSE: LicenseStatus = {
  state: 'unlicensed', allowed: false, plan: null, features: [],
  expires_at: null, grace_deadline: null, detail: null,
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SignUpPanel license={LICENSE} onSwitch={() => {}} />
    </QueryClientProvider>,
  );
}

describe('SignUpPanel', () => {
  it('blocks submit when the passwords do not match', async () => {
    const spy = vi.spyOn(api, 'accountRegister');
    renderPanel();
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co');
    const [pw, confirm] = screen.getAllByLabelText(/password/i);
    await userEvent.type(pw, 'correct horse battery staple');
    await userEvent.type(confirm, 'different password entirely');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(spy).not.toHaveBeenCalled();
  });

  it('registers when the form is valid', async () => {
    const spy = vi.spyOn(api, 'accountRegister').mockResolvedValue({ ...LICENSE, state: 'active', allowed: true, plan: 'trial' });
    renderPanel();
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co');
    const [pw, confirm] = screen.getAllByLabelText(/password/i);
    await userEvent.type(pw, 'correct horse battery staple');
    await userEvent.type(confirm, 'correct horse battery staple');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ email: 'a@b.co', password: 'correct horse battery staple' }),
    );
  });
});
