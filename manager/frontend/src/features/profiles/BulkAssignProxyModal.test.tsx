import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { toProfileView } from './view';
import { BulkAssignProxyModal } from './BulkAssignProxyModal';

beforeEach(() => mockStore.reset());

function views(n: number) {
  return mockStore.profiles
    .slice(0, n)
    .map((p) =>
      toProfileView(p, { tags: mockStore.tags, statuses: mockStore.statuses, proxies: mockStore.proxies }, {}),
    );
}

describe('BulkAssignProxyModal', () => {
  it('creates and assigns one proxy per selected profile from the pasted list', async () => {
    const user = userEvent.setup();
    const before = mockStore.proxies.length;
    renderWithProviders(
      <BulkAssignProxyModal open onClose={() => undefined} profiles={views(2)} />,
    );

    await user.type(
      screen.getByPlaceholderText(/host:port:user:pass/i),
      '1.1.1.1:1080:a:b\n2.2.2.2:1080:c:d',
    );
    await user.click(screen.getByRole('button', { name: /^assign$/i }));

    await waitFor(() => expect(mockStore.proxies.length).toBe(before + 2));
  });
});
