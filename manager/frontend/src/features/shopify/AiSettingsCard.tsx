import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { Button } from '@/components/ui/Button';
import { useT } from '@/i18n';
import { useAiSettings, useUpdateAiSettings } from './api';

const MODEL_OPTIONS = [
  { value: 'gpt-image-2', label: 'gpt-image-2' },
  { value: 'gpt-image-1', label: 'gpt-image-1' },
];

export function AiSettingsCard() {
  const t = useT();
  const settings = useAiSettings();
  const update = useUpdateAiSettings();

  const [enabled, setEnabled] = useState(false);
  const [model, setModel] = useState('gpt-image-2');
  const [key, setKey] = useState('');

  useEffect(() => {
    if (settings.data) {
      setEnabled(settings.data.enabled);
      setModel(settings.data.model);
    }
  }, [settings.data]);

  const save = () => {
    update.mutate({ enabled, model, api_key: key || undefined });
  };

  return (
    <section className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-3 flex items-center gap-1.5 text-ink">
        <Sparkles className="h-4 w-4 text-accent" />
        <h3 className="font-display text-[15px] font-semibold text-ink">{t('shop.ai.title')}</h3>
      </div>
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-[13px] text-ink">{t('shop.ai.enabled')}</span>
          <Toggle checked={enabled} onChange={setEnabled} label={t('shop.ai.enabled')} />
        </div>
        <Field label={t('shop.ai.model')}>
          <Select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            options={MODEL_OPTIONS}
          />
        </Field>
        <Field
          label={t('shop.ai.apiKey')}
          hint={settings.data?.has_api_key ? t('shop.ai.apiKeySet') : undefined}
        >
          <Input
            type="password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
        </Field>
        <Button variant="primary" size="sm" onClick={save} loading={update.isPending}>
          {t('shop.ai.save')}
        </Button>
      </div>
    </section>
  );
}
