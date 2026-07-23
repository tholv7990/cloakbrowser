import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { RuntimeState } from '@/types/api';
import { PlasmaIcon, RuntimeBadge } from './StatusBadges';

const STATES: RuntimeState[] = [
  'queued',
  'stopped',
  'starting',
  'running',
  'stopping',
  'crashed',
  'detached',
];

const LABELS: Record<RuntimeState, string> = {
  queued: 'Queued',
  stopped: 'Stopped',
  starting: 'Starting',
  running: 'Running',
  stopping: 'Stopping',
  crashed: 'Crashed',
  detached: 'Detached',
};

describe('RuntimeBadge', () => {
  it.each(STATES)('uses the plasma mark only for the %s state', (state) => {
    const { container } = render(<RuntimeBadge state={state} />);

    expect(screen.getByText(LABELS[state])).toBeInTheDocument();
    if (state === 'running') {
      expect(container.querySelector('svg')).toBeInTheDocument();
      expect(container.querySelector('g.animate-spin')).toBeInTheDocument();
    } else {
      expect(container.querySelector('svg')).not.toBeInTheDocument();
      expect(container.querySelector('g.animate-spin')).not.toBeInTheDocument();
    }
  });

  it('keeps non-running badges on their status-dot tones', () => {
    const expectedTone: Partial<Record<RuntimeState, string>> = {
      queued: 'text-info',
      stopped: 'text-ink-muted',
      starting: 'text-info',
      stopping: 'text-warning',
      crashed: 'text-danger',
      detached: 'text-warning',
    };

    for (const [state, tone] of Object.entries(expectedTone) as [RuntimeState, string][]) {
      const { container, unmount } = render(<RuntimeBadge state={state} />);
      expect(container.firstElementChild).toHaveClass(tone);
      expect(container.querySelector('svg')).not.toBeInTheDocument();
      expect(container.querySelector('.relative.inline-flex.h-2.w-2')).toBeInTheDocument();
      unmount();
    }
  });
});

describe('PlasmaIcon', () => {
  it('is decorative, inherits currentColor, and disables both animations for reduced motion', () => {
    const { container } = render(<PlasmaIcon />);
    const svg = container.querySelector('svg');
    const halo = container.querySelector('circle.animate-pulse');
    const orbit = container.querySelector('g.animate-spin');

    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelectorAll('[fill="currentColor"]')).toHaveLength(2);
    expect(orbit).toHaveAttribute('stroke', 'currentColor');
    expect(halo).toHaveClass('motion-reduce:animate-none');
    expect(orbit).toHaveClass('motion-reduce:animate-none');
  });
});
