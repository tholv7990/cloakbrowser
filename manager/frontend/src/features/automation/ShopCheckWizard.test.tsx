import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { api } from '@/api';
import type { ShopCheckRunCreateResult } from '@/types/api';
import { ShopCheckWizard } from './ShopCheckWizard';

const RESULT = {
  run: { id: 'run_1', workers: [] },
  input_summary: {},
} as unknown as ShopCheckRunCreateResult;

describe('ShopCheckWizard', () => {
  it('previews valid / duplicate / invalid counts as you type', async () => {
    renderWithProviders(<ShopCheckWizard open onClose={() => {}} onStarted={() => {}} />);
    await userEvent.type(
      screen.getByLabelText(/authorized accounts/i),
      'a@b.com\na@b.com\nnope\nc@d.com',
    );
    // 2 valid (a@b.com, c@d.com), 1 duplicate, 1 invalid.
    expect(screen.getByText('valid').previousSibling).toHaveTextContent('2');
    expect(screen.getByText('duplicates').previousSibling).toHaveTextContent('1');
    expect(screen.getByText('invalid').previousSibling).toHaveTextContent('1');
  });

  it('keeps start disabled until there are valid emails and the ack is checked', async () => {
    renderWithProviders(<ShopCheckWizard open onClose={() => {}} onStarted={() => {}} />);
    const start = screen.getByRole('button', { name: /start check/i });
    expect(start).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/authorized accounts/i), 'a@b.com');
    expect(start).toBeDisabled(); // still needs the ack
    await userEvent.click(screen.getByRole('checkbox'));
    expect(start).toBeEnabled();
  });

  it('submits the run payload and reports the new run id', async () => {
    const spy = vi.spyOn(api, 'createShopCheckRun').mockResolvedValue(RESULT);
    const onStarted = vi.fn();
    renderWithProviders(<ShopCheckWizard open onClose={() => {}} onStarted={onStarted} />);
    await userEvent.type(screen.getByLabelText(/authorized accounts/i), 'a@b.com\nc@d.com');
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: /start check/i }));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy).toHaveBeenCalledWith({
      email_text: 'a@b.com\nc@d.com',
      emails_per_profile: 5,
      max_parallel: 3,
      region: null,
      profile_prefix: null,
      authorized_only_ack: true,
    });
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith('run_1'));
  });
});
