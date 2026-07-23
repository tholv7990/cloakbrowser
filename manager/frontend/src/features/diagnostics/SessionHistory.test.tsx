import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import type { RuntimeSessionRecord } from '@/types/api';
import { useUiStore, type Language } from '@/app/uiStore';
import { renderWithProviders } from '@/test/utils';
import { en } from '@/i18n/en';
import { vi as viDictionary } from '@/i18n/vi';
import { useSessions } from './api';
import { SessionHistory } from './SessionHistory';

vi.mock('./api', () => ({ useSessions: vi.fn() }));

const mockedUseSessions = vi.mocked(useSessions);

function sessions(count: number): RuntimeSessionRecord[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `session-${index + 1}`,
    profile_id: `profile-${index + 1}`,
    profile_name: `Profile ${index + 1}`,
    started_at: '2026-07-23T00:00:00.000Z',
    ended_at: '2026-07-23T00:05:00.000Z',
    duration_seconds: 300,
    startup_ms: 500,
    exit_reason: 'closed',
  }));
}

function provideSessions(rows: RuntimeSessionRecord[]): void {
  mockedUseSessions.mockReturnValue({
    data: rows,
    isLoading: false,
  } as unknown as ReturnType<typeof useSessions>);
}

function tableRows(): HTMLElement[] {
  const table = screen.queryByRole('table');
  return table ? within(table).queryAllByRole('row').slice(1) : [];
}

describe('SessionHistory pagination', () => {
  beforeEach(() => {
    useUiStore.setState({ language: 'en' });
    provideSessions([]);
  });

  it.each([0, 8])('does not render a pager for %i sessions', (count) => {
    provideSessions(sessions(count));
    renderWithProviders(<SessionHistory />);

    expect(screen.queryByLabelText('Next page')).not.toBeInTheDocument();
    expect(tableRows()).toHaveLength(count);
  });

  it('shows two pages for nine sessions and navigates to the remainder', () => {
    provideSessions(sessions(9));
    renderWithProviders(<SessionHistory />);

    const previous = screen.getByLabelText('Previous page');
    const next = screen.getByLabelText('Next page');
    expect(tableRows()).toHaveLength(8);
    expect(screen.getByText('Showing 1–8 of 9')).toBeInTheDocument();
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();

    fireEvent.click(next);
    expect(tableRows()).toHaveLength(1);
    expect(screen.getByText('Profile 9')).toBeInTheDocument();
    expect(screen.getByText('Showing 9–9 of 9')).toBeInTheDocument();
    expect(screen.getByText('2 / 2')).toBeInTheDocument();
    expect(previous).toBeEnabled();
    expect(next).toBeDisabled();

    fireEvent.click(previous);
    expect(tableRows()).toHaveLength(8);
    expect(screen.getByText('Showing 1–8 of 9')).toBeInTheDocument();
  });

  it('moves through twenty sessions in windows of eight', () => {
    provideSessions(sessions(20));
    renderWithProviders(<SessionHistory />);

    expect(tableRows()).toHaveLength(8);
    expect(screen.getByText('Showing 1–8 of 20')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Next page'));
    expect(tableRows()).toHaveLength(8);
    expect(screen.getByText('Showing 9–16 of 20')).toBeInTheDocument();
    expect(screen.getByText('2 / 3')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Next page'));
    expect(tableRows()).toHaveLength(4);
    expect(screen.getByText('Showing 17–20 of 20')).toBeInTheDocument();
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    expect(screen.getByLabelText('Next page')).toBeDisabled();
  });

  it('clamps the visible page when the session count shrinks', () => {
    provideSessions(sessions(20));
    const view = renderWithProviders(<SessionHistory />);
    fireEvent.click(screen.getByLabelText('Next page'));
    fireEvent.click(screen.getByLabelText('Next page'));
    expect(screen.getByText('3 / 3')).toBeInTheDocument();

    provideSessions(sessions(9));
    view.rerender(<SessionHistory />);

    expect(tableRows()).toHaveLength(1);
    expect(screen.getByText('Profile 9')).toBeInTheDocument();
    expect(screen.getByText('Showing 9–9 of 9')).toBeInTheDocument();
    expect(screen.getByText('2 / 2')).toBeInTheDocument();
  });

  it.each([
    ['en', en, 'Showing 1–8 of 9'],
    ['vi', viDictionary, 'Hiển thị 1–8 trong 9'],
  ] as const)(
    'defines and interpolates the pager translations in %s',
    (language: Language, dictionary, expected) => {
      expect(dictionary['sess.page.showing']).toContain('{from}');
      expect(dictionary['sess.page.showing']).toContain('{to}');
      expect(dictionary['sess.page.showing']).toContain('{total}');
      expect(dictionary['sess.page.prev']).toBeTruthy();
      expect(dictionary['sess.page.next']).toBeTruthy();

      useUiStore.setState({ language });
      provideSessions(sessions(9));
      renderWithProviders(<SessionHistory />);
      expect(screen.getByText(expected)).toBeInTheDocument();
    },
  );
});
