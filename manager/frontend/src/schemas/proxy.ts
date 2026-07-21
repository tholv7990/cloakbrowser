import { z } from 'zod';
import type { ProxyWritePayload } from '@/types/api';

export const proxySchemes = ['direct', 'http', 'https', 'socks5', 'socks5h'] as const;

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
