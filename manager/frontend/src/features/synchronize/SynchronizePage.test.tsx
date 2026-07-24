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
  it('lists running + detached profiles and arranges them on Tile', async () => {
    vi.spyOn(api, 'listProfiles').mockResolvedValue({
      items: [
        { id: 'p1', name: 'Alpha', runtime_state: 'running' },
        { id: 'p2', name: 'Beta', runtime_state: 'stopped' },
        // 'detached' = a live window the manager reconnected to; must be tileable.
        { id: 'p3', name: 'Gamma', runtime_state: 'detached' },
      ],
      total: 3,
    } as never);
    const arrange = vi.spyOn(api, 'arrangeWindows').mockResolvedValue({
      results: [
        { profile_id: 'p1', ok: true, error: null },
        { profile_id: 'p3', ok: true, error: null },
      ],
    });

    renderPage();

    // Both the running and the detached profile appear; the stopped one does not.
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(await screen.findByText('Gamma')).toBeInTheDocument();
    expect(screen.queryByText('Beta')).not.toBeInTheDocument();

    // Tile stays disabled until a monitor has actually loaded (mock monitors
    // resolve slightly after profiles) — wait for it to become clickable, the
    // same way a real user would have to.
    const tileButton = screen.getByRole('button', { name: /tile windows/i });
    await waitFor(() => expect(tileButton).toBeEnabled());
    await userEvent.click(tileButton);

    await waitFor(() =>
      expect(arrange).toHaveBeenCalledWith(
        expect.objectContaining({ profile_ids: ['p1', 'p3'], layout: 'grid' }),
      ),
    );
  });
});
