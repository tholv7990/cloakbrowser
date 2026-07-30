/**
 * Client-side email-paste parsing for the Shop-check wizard's live preview and
 * the mock API. The backend re-validates authoritatively on submit; this is only
 * for immediate feedback, so it mirrors the backend's rules loosely: a simple
 * address shape, case-insensitive dedupe, blanks ignored. Never logged.
 */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export interface ParsedEntry {
  line: number;
  masked: string;
  reason?: string;
}
export interface ParsedInput {
  totalLines: number;
  valid: string[]; // normalized addresses
  duplicates: ParsedEntry[];
  invalid: ParsedEntry[];
}

/** Mask an address for display: first char of local part + domain kept. */
export function maskEmail(address: string): string {
  const [local, domain] = address.split('@');
  if (!domain) return '•••';
  const head = local.slice(0, 1);
  return `${head}${'•'.repeat(Math.max(1, local.length - 1))}@${domain}`;
}

export function parseShopCheckEmails(text: string): ParsedInput {
  const valid: string[] = [];
  const duplicates: ParsedEntry[] = [];
  const invalid: ParsedEntry[] = [];
  const seen = new Set<string>();
  let totalLines = 0;

  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim();
    if (!line) return;
    totalLines += 1;
    const lineNo = index + 1;
    if (!EMAIL_RE.test(line)) {
      invalid.push({ line: lineNo, masked: maskEmail(line), reason: 'invalid_format' });
      return;
    }
    const normalized = line.toLowerCase();
    if (seen.has(normalized)) {
      duplicates.push({ line: lineNo, masked: maskEmail(normalized) });
      return;
    }
    seen.add(normalized);
    valid.push(normalized);
  });

  return { totalLines, valid, duplicates, invalid };
}

/** Workers = one per `perProfile` valid emails (matches backend grouping). */
export function workerCount(validCount: number, perProfile: number): number {
  if (validCount <= 0 || perProfile <= 0) return 0;
  return Math.ceil(validCount / perProfile);
}
