import { z } from 'zod';
import type { ProxyWritePayload } from '@/types/api';

export const proxySchemes = ['direct', 'http', 'https', 'socks5', 'socks5h'] as const;

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
    }
  });

export type ProxyFormValues = z.input<typeof proxyFormSchema>;

export function toProxyPayload(values: z.output<typeof proxyFormSchema>): ProxyWritePayload {
  return {
    label: values.label,
    scheme: values.scheme,
    host: values.scheme === 'direct' ? '' : values.host,
    port: values.scheme === 'direct' ? null : values.port,
    username: values.username || null,
    // Only send a password when the user typed one (write-only field).
    password: values.password ? values.password : undefined,
    test_before_launch: values.test_before_launch,
  };
}
