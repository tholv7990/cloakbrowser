import { beforeEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { mockStore } from '@/mocks/store';
import { NewProfileModal } from './NewProfileModal';

beforeEach(() => mockStore.reset());

describe('NewProfileModal', () => {
  it('creates a single named profile', async () => {
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Solo');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 1));
    expect(mockStore.profiles.some((p) => p.name === 'Solo')).toBe(true);
  });

  it('creates a numbered batch when count > 1', async () => {
    const user = userEvent.setup();
    const before = mockStore.profiles.length;
    renderWithProviders(<NewProfileModal open onClose={() => undefined} folders={[]} />);

    await user.type(screen.getByPlaceholderText(/marketplace/i), 'Batch');
    const count = screen.getByRole('spinbutton');
    await user.clear(count);
    await user.type(count, '3');
    await user.click(screen.getByRole('button', { name: /create all/i }));

    await waitFor(() => expect(mockStore.profiles.length).toBe(before + 3));
    const names = mockStore.profiles.map((p) => p.name);
    expect(names).toContain('Batch 01');
    expect(names).toContain('Batch 03');
  });
});
