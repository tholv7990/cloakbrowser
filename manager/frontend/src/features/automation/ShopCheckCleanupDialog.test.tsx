import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { api } from '@/api';
import type { ShopCheckRunDetail, ShopCheckWorkerRead } from '@/types/api';
import { ShopCheckCleanupDialog } from './ShopCheckCleanupDialog';

function worker(ordinal: number, profileId: string | null): ShopCheckWorkerRead {
  return {
    id: `w${ordinal}`,
    ordinal,
    state: 'terminal',
    profile_id: profileId,
    proxy_id: profileId ? `x${ordinal}` : null,
    assigned_count: 5,
    processed_count: 5,
    error: null,
  };
}

const RUN = {
  id: 'run_1',
  status: 'completed',
  cleanup_state: 'none',
  // 2 owned profiles, 1 worker that never got one.
  workers: [worker(0, 'p0'), worker(1, 'p1'), worker(2, null)],
} as unknown as ShopCheckRunDetail;

describe('ShopCheckCleanupDialog', () => {
  it('shows the exact owned-profile count and gates on confirmation', async () => {
    renderWithProviders(<ShopCheckCleanupDialog run={RUN} open onClose={() => {}} />);
    const del = screen.getByRole('button', { name: /delete 2 profiles/i });
    expect(del).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox'));
    expect(del).toBeEnabled();
  });

  it('calls only the run cleanup endpoint with the displayed count', async () => {
    const spy = vi.spyOn(api, 'cleanupShopCheckRun').mockResolvedValue({
      run_id: 'run_1',
      cleanup_state: 'done',
      requested: 2,
      deleted: 2,
      failed: 0,
      profiles: [],
    });
    const onClose = vi.fn();
    renderWithProviders(<ShopCheckCleanupDialog run={RUN} open onClose={onClose} />);
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: /delete 2 profiles/i }));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy).toHaveBeenCalledWith('run_1', { confirm: true, expected_profile_count: 2 });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
