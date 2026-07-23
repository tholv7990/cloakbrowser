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

/** ISO 3166-1 alpha-2 country code -> flag emoji ("US" -> "🇺🇸"). Empty string
 *  for anything that isn't a two-letter code, so callers can fall back. */
export function countryFlag(code: string | null | undefined): string {
  if (!code || !/^[a-zA-Z]{2}$/.test(code)) return '';
  return String.fromCodePoint(
    ...[...code.toUpperCase()].map((letter) => 0x1f1e6 + letter.charCodeAt(0) - 65),
  );
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes < 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export const personaLabel: Record<'windows_10' | 'windows_11', string> = {
  windows_10: 'Windows 10',
  windows_11: 'Windows 11',
};
