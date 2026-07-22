import { useState } from 'react';
import { KeyRound, Upload } from 'lucide-react';
import { Field } from '@/components/ui/Field';
import { Textarea } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { useT } from '@/i18n';
import { useCredentialPool, useImportCredentials } from './api';

export function CredentialsPanel() {
  const t = useT();
  const pool = useCredentialPool();
  const importCreds = useImportCredentials();
  const [text, setText] = useState('');

  const stats: [string, number | undefined][] = [
    [t('auto.cred.available'), pool.data?.available],
    [t('auto.cred.reserved'), pool.data?.reserved],
    [t('auto.cred.used'), pool.data?.used],
    [t('auto.cred.failed'), pool.data?.failed],
  ];

  const submit = () => {
    if (text.trim()) importCreds.mutate(text, { onSuccess: () => setText('') });
  };

  return (
    <section className="space-y-4">
      <div>
        <div className="mb-1 flex items-center gap-1.5 text-ink">
          <KeyRound className="h-4 w-4 text-accent" />
          <h2 className="font-display text-[15px] font-semibold">{t('auto.cred.title')}</h2>
        </div>
        <p className="text-2xs text-ink-faint">{t('auto.cred.desc')}</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md border border-line bg-surface-sunken p-3">
            <p className="font-display text-lg font-semibold tabular-nums text-ink">{value ?? '—'}</p>
            <p className="text-2xs text-ink-faint">{label}</p>
          </div>
        ))}
      </div>
      <Field label={t('auto.cred.import')}>
        <Textarea
          rows={5}
          className="font-mono text-[12px]"
          placeholder={'user@example.com:password'}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </Field>
      <Button variant="primary" onClick={submit} loading={importCreds.isPending} disabled={!text.trim()}>
        <Upload className="h-3.5 w-3.5" /> {t('auto.cred.import')}
      </Button>
    </section>
  );
}
