import 'flag-icons/css/flag-icons.min.css';

/**
 * A real SVG country flag (flag-icons CSS sprite).
 *
 * WebView2 / Chromium on Windows does NOT render emoji regional-indicator flags
 * (they show as the two letters), so the old `countryFlag()` emoji helper looked
 * like "us US". This uses flag-icons' bundled SVGs instead, which render on every
 * platform. Renders nothing for a missing / non-two-letter code so callers can
 * fall back to text.
 */
export function CountryFlag({
  code,
  className = '',
}: {
  code?: string | null;
  className?: string;
}) {
  if (!code || !/^[a-zA-Z]{2}$/.test(code)) return null;
  return (
    <span
      className={`fi fi-${code.toLowerCase()} rounded-[2px] ${className}`}
      aria-hidden="true"
    />
  );
}

export default CountryFlag;
