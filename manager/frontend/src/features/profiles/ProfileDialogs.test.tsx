import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import { mockApi } from '@/mocks/mockApi';
import { mockStore } from '@/mocks/store';
import { toProfileView } from './view';
import { ProfileDialogs } from './ProfileDialogs';

function profileView() {
  return toProfileView(
    mockStore.profiles[0],
    { tags: mockStore.tags, statuses: mockStore.statuses, proxies: mockStore.proxies },
    {},
  );
}

describe('ProfileDialogs', () => {
  beforeEach(() => mockStore.reset());

  it('uses visible page controls and sends log pagination parameters', async () => {
    const user = userEvent.setup();
    const logs = vi.spyOn(mockApi, 'getProfileLogs').mockImplementation(async (_id, params) => ({
      items: [
        {
          id: `log-${params?.page ?? 1}`,
          profile_id: mockStore.profiles[0].id,
          created_at: '2026-07-22T00:00:00Z',
          level: 'info',
          event: 'runtime.ready',
          message: `page ${params?.page ?? 1}`,
        },
      ],
      total: 40,
      page: params?.page ?? 1,
      page_size: params?.page_size ?? 20,
      pages: 2,
    }));
    const tail = vi.spyOn(mockApi, 'getProfileLogTail').mockResolvedValue({
      items: [
        {
          id: 'tail-1',
          profile_id: mockStore.profiles[0].id,
          created_at: '2026-07-22T00:00:00Z',
          level: 'info',
          event: 'runtime.ready',
          message: 'page 1',
        },
      ],
      next_cursor: 'opaque-cursor',
      reset: false,
    });
    renderWithProviders(
      <ProfileDialogs
        dialog={{ type: 'logs', profile: profileView() }}
        onClose={() => undefined}
        folders={mockStore.folders}
        proxies={mockStore.proxies}
      />,
    );

    expect(await screen.findByText('page 1')).toBeInTheDocument();
    expect(tail).toHaveBeenCalledWith(
      mockStore.profiles[0].id,
      expect.objectContaining({ limit: 20 }),
    );
    await user.click(screen.getByRole('button', { name: /next log page/i }));
    expect(await screen.findByText('page 2')).toBeInTheDocument();
    await waitFor(() =>
      expect(logs).toHaveBeenLastCalledWith(
        mockStore.profiles[0].id,
        expect.objectContaining({ page: 2, page_size: 20 }),
      ),
    );
  });

  it('opens the proxy form directly for assign-proxy (no intermediate dialog)', async () => {
    renderWithProviders(
      <ProfileDialogs
        dialog={{ type: 'assign-proxy', profile: profileView() }}
        onClose={() => undefined}
        folders={mockStore.folders}
        proxies={mockStore.proxies}
      />,
    );
    // The editable proxy form is on screen immediately — no "Assign proxy" picker,
    // no "Add new proxy" step to click through first.
    expect(await screen.findByPlaceholderText(/residential/i)).toBeInTheDocument();
    expect(screen.queryByText(/add new proxy/i)).not.toBeInTheDocument();
  });

  it('reports rejected cookies separately from skipped cookies', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ProfileDialogs
        dialog={{ type: 'import-cookies', profile: profileView() }}
        onClose={() => undefined}
        folders={mockStore.folders}
        proxies={mockStore.proxies}
      />,
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '[]' } });
    await user.click(screen.getByRole('button', { name: /^import$/i }));
    expect(await screen.findByText(/rejected:\s*0/i)).toBeInTheDocument();
  });
});
