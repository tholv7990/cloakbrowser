import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { api } from '@/api';
import type { Paginated, ShopCheckEmailRead, ShopCheckRunDetail } from '@/types/api';
import { ShopCheckRunView } from './ShopCheckRunView';

const RUN = {
  id: 'run_1',
  status: 'completed_with_issues',
  region: 'US',
  emails_per_profile: 5,
  max_parallel: 3,
  target_url: 'https://shop.app/',
  total_emails: 3,
  terminal_count: 3,
  retryable_count: 1,
  worker_count: 1,
  cleanup_state: 'none',
  result_counts: { phone_otp_required: 2, unknown: 1 },
  created_at: '2026-07-30T00:00:00Z',
  started_at: '2026-07-30T00:00:00Z',
  finished_at: '2026-07-30T00:01:00Z',
  profile_prefix: null,
  output_dir: null,
  error: null,
  workers: [
    {
      id: 'w0',
      ordinal: 0,
      state: 'terminal',
      profile_id: 'p0',
      proxy_id: 'x0',
      assigned_count: 3,
      processed_count: 3,
      error: null,
    },
  ],
} as ShopCheckRunDetail;

const EMAILS: Paginated<ShopCheckEmailRead> = {
  items: [
    {
      id: 'e0',
      ordinal: 0,
      email_masked: 'a•••@b.com',
      state: 'terminal',
      result: 'phone_otp_required',
      retryable: false,
      phone_prefix: '+84',
      phone_suffix: '34',
      phone_country_code: 'VN',
      phone_country_name: 'Vietnam',
      phone_region_name: null,
      phone_confidence: 'exact',
      retry_count: 0,
      worker_id: 'w0',
      checked_at: '2026-07-30T00:00:30Z',
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
  pages: 1,
};

describe('ShopCheckRunView', () => {
  it('renders status, aggregate outcomes, the completion banner, and a masked email', async () => {
    vi.spyOn(api, 'getShopCheckRun').mockResolvedValue(RUN);
    vi.spyOn(api, 'listShopCheckEmails').mockResolvedValue(EMAILS);
    renderWithProviders(<ShopCheckRunView runId="run_1" onBack={() => {}} />);

    expect(await screen.findByText(/completed with issues/i)).toBeInTheDocument();
    // aggregate badge shows the matched count
    expect(await screen.findByText(/phone otp · 2/i)).toBeInTheDocument();
    // persistent banner: 2 of 3 need a phone code
    expect(screen.getByText(/2 of 3 require a phone code/i)).toBeInTheDocument();
    // the masked address, never a full email
    expect(await screen.findByText('a•••@b.com')).toBeInTheDocument();
    expect(screen.getByText(/Vietnam/)).toBeInTheDocument();
  });

  it('exports through the run export endpoint', async () => {
    vi.spyOn(api, 'getShopCheckRun').mockResolvedValue(RUN);
    vi.spyOn(api, 'listShopCheckEmails').mockResolvedValue(EMAILS);
    const spy = vi.spyOn(api, 'exportShopCheckRun').mockResolvedValue({
      run_id: 'run_1',
      output_dir: 'exports/run_1',
      results_csv: 'exports/run_1/results.csv',
      matched_txt: 'exports/run_1/matched.txt',
      total_rows: 3,
      matched_count: 2,
    });
    renderWithProviders(<ShopCheckRunView runId="run_1" onBack={() => {}} />);
    await userEvent.click(await screen.findByRole('button', { name: /export/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith('run_1'));
  });
});
