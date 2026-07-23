import { useState } from 'react';
import { XCircle, Zap } from 'lucide-react';
import type { ProxyQuickTest, ProxyScheme } from '@/types/api';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { parseProxyText, proxySchemes } from '@/schemas/proxy';
import { useQuickTestAdhoc } from './api';
import { ProxyQuickResult } from './ProxyResultViews';

/** Structured single-proxy value (port/creds kept as strings for the inputs). */
export interface OneProxy {
  scheme: ProxyScheme;
  host: string;
  port: string;
  username: string;
  password: string;
}

export const emptyOneProxy: OneProxy = {
  scheme: 'http',
  host: '',
  port: '',
  username: '',
  password: '',
};

// Selectable proxy transports (drop "direct" — that's the "no proxy" choice).
const schemeOptions = proxySchemes
  .filter((s) => s !== 'direct')
  .map((s) => ({ value: s, label: s.toUpperCase() }));

/**
 * Inline single-proxy form (BitBrowser style), stacked one control per row:
 * Type → a paste line → the parsed host/port → the parsed user/pass. Pasting a
 * full `host:port:user:pass` (or `scheme://user:pass@host:port`) into the paste
 * line fills the fields below, which stay editable. Check runs the ad-hoc
 * quick-test (nothing is persisted) and shows the full result. The chosen scheme
 * is authoritative, so a SOCKS5 proxy is tested and launched as SOCKS5.
 *
 * Controlled: the caller owns the value and decides when to persist it.
 */
export function ProxyInlineForm({
  value,
  onChange,
}: {
  value: OneProxy;
  onChange: (v: OneProxy) => void;
}) {
  const t = useT();
  const test = useQuickTestAdhoc();
  const [result, setResult] = useState<ProxyQuickTest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pasteText, setPasteText] = useState('');

  const set = (patch: Partial<OneProxy>) => onChange({ ...value, ...patch });

  // The paste line fills the parsed fields below (keeping the current scheme
  // unless the pasted string carries its own scheme://).
  const onPaste = (raw: string) => {
    setPasteText(raw);
    const parsed = parseProxyText(raw);
    if (parsed?.host && parsed.port) {
      onChange({
        scheme: parsed.scheme ?? value.scheme,
        host: parsed.host,
        port: parsed.port,
        username: parsed.username,
        password: parsed.password,
      });
    }
  };

  const canCheck = Boolean(value.host.trim() && value.port.trim());
  const check = async () => {
    setError(null);
    setResult(null);
    try {
      setResult(
        await test.mutateAsync({
          scheme: value.scheme,
          host: value.host.trim(),
          port: Number(value.port),
          username: value.username.trim() || null,
          password: value.password || null,
        }),
      );
    } catch (e) {
      setError((e as Error).message || t('new.proxyTestFailed'));
    }
  };

  return (
    <div className="space-y-2.5 rounded-md border border-line bg-surface-sunken p-3">
      <Field label={t('new.proxyType')}>
        <Select
          value={value.scheme}
          onChange={(e) => set({ scheme: e.target.value as ProxyScheme })}
          options={schemeOptions}
        />
      </Field>
      <Field label={t('new.proxyPaste')} hint={t('new.proxyPasteHint')}>
        <Input
          value={pasteText}
          onChange={(e) => onPaste(e.target.value)}
          placeholder="host:port:user:pass"
          className="font-mono text-[12px]"
        />
      </Field>
      <div className="grid grid-cols-[1fr_96px] gap-2">
        <Field label={t('pxd.host')}>
          <Input value={value.host} onChange={(e) => set({ host: e.target.value })} placeholder="proxy.example" mono />
        </Field>
        <Field label={t('pxd.port')}>
          <Input
            value={value.port}
            onChange={(e) => set({ port: e.target.value.replace(/[^\d]/g, '') })}
            placeholder="1080"
            inputMode="numeric"
            mono
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label={t('pxd.username')}>
          <Input value={value.username} onChange={(e) => set({ username: e.target.value })} autoComplete="off" />
        </Field>
        <Field label={t('auth.password')}>
          <Input value={value.password} onChange={(e) => set({ password: e.target.value })} autoComplete="off" mono />
        </Field>
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={check} disabled={!canCheck} loading={test.isPending}>
          <Zap className="h-3.5 w-3.5" /> {t('new.proxyCheck')}
        </Button>
        {test.isPending && <span className="text-2xs text-ink-faint">{t('new.proxyChecking')}</span>}
      </div>
      {error && (
        <p className="flex items-center gap-1.5 text-2xs text-danger">
          <XCircle className="h-3.5 w-3.5" /> {error}
        </p>
      )}
      {result && <ProxyQuickResult result={result} />}
    </div>
  );
}
