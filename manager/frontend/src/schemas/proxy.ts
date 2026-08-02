import { z } from 'zod';
import type { ProxyWritePayload } from '@/types/api';

export const proxySchemes = ['direct', 'http', 'https', 'socks5', 'socks5h'] as const;

export const proxyResponseSchema = z
  .object({
    id: z.string(),
    label: z.string(),
    scheme: z.enum(proxySchemes),
    host: z.string(),
    port: z.number().int().nullable(),
    username: z.string().nullable(),
    has_password: z.boolean(),
    masked_endpoint: z.string(),
    test_before_launch: z.boolean(),
    assigned_profile_count: z.number().int().nonnegative(),
    exit_ip: z.string().nullable(),
    country: z.string().nullable(),
    city: z.string().nullable(),
    timezone: z.string().nullable(),
    asn: z.string().nullable(),
    organization: z.string().nullable(),
    proxy_type: z
      .enum(['residential', 'datacenter', 'mobile', 'isp', 'hosting', 'unknown'])
      .nullable(),
    type_confidence: z.number().nullable(),
    reputation: z.enum(['clean', 'neutral', 'suspicious', 'malicious', 'unknown']).nullable(),
    latency_ms: z.number().int().nullable(),
    last_checked_at: z.string().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();

export interface ParsedProxyText {
  scheme?: (typeof proxySchemes)[number];
  host: string;
  port: string;
  username: string;
  password: string;
}

function normalizeScheme(value: string): (typeof proxySchemes)[number] | undefined {
  const lower = value.toLowerCase();
  return (proxySchemes as readonly string[]).includes(lower)
    ? (lower as (typeof proxySchemes)[number])
    : undefined;
}

/**
 * Client-side parse of a pasted proxy string into all four fields (incl. the
 * plaintext password, which the server parser never returns). Accepts:
 *   scheme://user:pass@host:port    and    host:port:user:pass
 * Returns null until the text has at least a host and numeric port.
 */
export function parseProxyText(raw: string): ParsedProxyText | null {
  const text = raw.trim();
  if (!text) return null;

  const url = text.match(/^([a-z0-9]+):\/\/(?:([^:@/]+):([^@/]*)@)?([^:/@]+):(\d+)\/?$/i);
  if (url) {
    const [, scheme, user, pass, host, port] = url;
    return { scheme: normalizeScheme(scheme), host, port, username: user ?? '', password: pass ?? '' };
  }

  // host:port[:user:pass] — password may itself contain ':'
  const parts = text.split(':');
  if (parts.length >= 2 && /^\d+$/.test(parts[1])) {
    return {
      host: parts[0],
      port: parts[1],
      username: parts[2] ?? '',
      password: parts.slice(3).join(':'),
    };
  }
  return null;
}

export const proxyFormSchema = z
  .object({
    label: z.string().trim().min(1, 'Give this proxy a label.').max(80),
    scheme: z.enum(proxySchemes),
    host: z.string().trim(),
    port: z
      .union([z.coerce.number().int().min(1).max(65535), z.literal('')])
      .transform((value) => (value === '' ? null : value))
      .nullable(),
    username: z.string().trim().max(200).nullable(),
    // Write-only. Empty string on edit means "leave the stored secret unchanged".
    password: z.string().max(400).optional(),
    clear_credentials: z.boolean().optional(),
    stored_username: z.string().nullable().default(null),
    has_stored_password: z.boolean().default(false),
    test_before_launch: z.boolean(),
  })
  .superRefine((value, ctx) => {
    if (value.scheme !== 'direct') {
      if (!value.host) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['host'], message: 'Host is required.' });
      }
      if (value.port == null) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['port'], message: 'Port is required.' });
      }

      if (!value.clear_credentials) {
        const username = value.username ?? '';
        const password = value.password ?? '';
        const preservesStoredCredential =
          value.has_stored_password && !password && username === value.stored_username;
        const hasCompleteReplacement = Boolean(username && password);
        const hasNoCredential = !value.has_stored_password && !username && !password;
        if (!preservesStoredCredential && !hasCompleteReplacement && !hasNoCredential) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['username'],
            message: 'Enter both username and password.',
          });
        }
      }
    }
  });

export type ProxyFormValues = z.input<typeof proxyFormSchema>;

export function toProxyPayload(values: z.output<typeof proxyFormSchema>): ProxyWritePayload {
  const isDirect = values.scheme === 'direct';
  const clearCredentials = values.clear_credentials === true;
  return {
    label: values.label,
    scheme: values.scheme,
    host: isDirect ? '' : values.host,
    port: isDirect ? null : values.port,
    // Direct mode forbids submitted credentials; stored credentials remain until
    // the user explicitly clears them.
    username: isDirect || clearCredentials ? null : values.username || null,
    // Only send a password when the user typed one (write-only field).
    password: isDirect || clearCredentials ? undefined : values.password ? values.password : undefined,
    clear_credentials: clearCredentials || undefined,
    test_before_launch: values.test_before_launch,
  };
}
