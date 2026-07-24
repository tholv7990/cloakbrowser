import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { SynchronizePage } from './SynchronizePage';
import { api } from '@/api';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SynchronizePage />
    </QueryClientProvider>,
  );
}

describe('SynchronizePage', () => {
  it('lists running profiles and arranges them on Tile', async () => {
    vi.spyOn(api, 'listProfiles').mockResolvedValue({
      items: [
        { id: 'p1', name: 'Alpha', runtime_state: 'running' },
        { id: 'p2', name: 'Beta', runtime_state: 'stopped' },
      ],
      total: 2,
    } as never);
    const arrange = vi
      .spyOn(api, 'arrangeWindows')
      .mockResolvedValue({ results: [{ profile_id: 'p1', ok: true, error: null }] });

    renderPage();

    // Only the running profile appears.
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(screen.queryByText('Beta')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /tile windows/i }));

    await waitFor(() =>
      expect(arrange).toHaveBeenCalledWith(
        expect.objectContaining({ profile_ids: ['p1'], layout: 'grid' }),
      ),
    );
  });
});
