/**
 * What the address bar actually does: navigate if it looks like a URL, otherwise
 * search. Typing in a profile's real address bar cannot be mirrored (it is browser
 * chrome with no DOM), so the sync box reproduces the *behaviour* instead.
 */
export function toNavigableUrl(input: string): string | null {
  const value = input.trim();
  if (!value) return null;

  // Already explicit — pass through, but only schemes we allow to navigate.
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    return /^https?:\/\//i.test(value) ? value : null;
  }
  // Reject a non-http scheme (javascript:, file:, data:). The negative lookahead
  // keeps "localhost:3000" / "host:8080" out of this branch — that colon is a port.
  if (/^[a-z][a-z0-9+.-]*:(?!\d)/i.test(value)) return null;

  // "example.com", "example.com/path", "localhost:3000" -> a bare host.
  const host = value.split(/[/?#]/, 1)[0];
  const looksLikeHost =
    !/\s/.test(value) && (/^[^\s.]+\.[^\s.]{2,}$/.test(host) || /^localhost(:\d+)?$/i.test(host));
  if (looksLikeHost) return `https://${value}`;

  return `https://www.google.com/search?q=${encodeURIComponent(value)}`;
}
