const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 60 * 60 * 24 * 365],
  ['month', 60 * 60 * 24 * 30],
  ['day', 60 * 60 * 24],
  ['hour', 60 * 60],
  ['minute', 60],
  ['second', 1],
];

/** "3 hours ago" / "just now". Returns "—" for null. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diffSeconds = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(diffSeconds);
  if (abs < 5) return 'just now';
  for (const [unit, secondsInUnit] of UNITS) {
    if (abs >= secondsInUnit || unit === 'second') {
      return RELATIVE.format(Math.round(diffSeconds / secondsInUnit), unit);
    }
  }
  return 'just now';
}

const DATE_TIME = new Intl.DateTimeFormat('en', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : DATE_TIME.format(date);
}

/** Compact display of a UUID-ish id (keeps a copyable full value elsewhere). */
export function shortId(id: string, length = 8): string {
  const bare = id.includes('-') ? id.split('-').slice(1).join('-') || id : id;
  return bare.length > length ? bare.slice(0, length) : bare;
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return '—';
  return `${Math.round(ms)} ms`;
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio == null) return '—';
  return `${Math.round(ratio * 100)}%`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`;
}

export const personaLabel: Record<'windows_10' | 'windows_11', string> = {
  windows_10: 'Windows 10',
  windows_11: 'Windows 11',
};
