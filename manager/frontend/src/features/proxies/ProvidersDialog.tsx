import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import type { ProxyProviderId } from '@/types/api';
import { Modal } from '@/components/ui/Modal';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { useT } from '@/i18n';
import { useConfigureProxyProvider, useGenerateProxies, useProxyProviders } from './api';

export function ProvidersDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const providers = useProxyProviders();
  const configure = useConfigureProxyProvider();
  const generate = useGenerateProxies();

  const [providerId, setProviderId] = useState<ProxyProviderId>('iproyal');
  const [apiToken, setApiToken] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [count, setCount] = useState(5);
  const [country, setCountry] = useState('US');
  const [sessionType, setSessionType] = useState<'rotating' | 'sticky'>('rotating');

  useEffect(() => {
    if (open) {
      setApiToken('');
      setUsername('');
      setPassword('');
    }
  }, [open, providerId]);

  const provider = (providers.data ?? []).find((p) => p.id === providerId);
  const isIproyal = providerId === 'iproyal';

  const saveCreds = () =>
    configure.mutate({
      provider: providerId,
      api_token: isIproyal ? apiToken : undefined,
      username: isIproyal ? undefined : username,
      password: isIproyal ? undefined : password,
    });

  const doGenerate = () =>
    generate.mutate(
      { provider: providerId, count, country: country.trim() || 'US', session_type: sessionType },
      { onSuccess: onClose },
    );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('prov.title')}
      description={t('prov.desc')}
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel')}
        </Button>
      }
    >
      <div className="space-y-4">
        <Field label={t('prov.provider')}>
          <div className="flex items-center gap-2">
            <Select
              className="flex-1"
              value={providerId}
              onChange={(e) => setProviderId(e.target.value as ProxyProviderId)}
              options={(providers.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
            />
            <Badge tone={provider?.configured ? 'success' : 'neutral'}>
              {provider?.configured ? t('prov.configured') : t('prov.notConfigured')}
            </Badge>
          </div>
        </Field>

        {isIproyal ? (
          <Field label={t('prov.apiToken')}>
            <Input type="password" value={apiToken} onChange={(e) => setApiToken(e.target.value)} />
          </Field>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('prov.username')}>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} />
            </Field>
            <Field label={t('prov.password')}>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </div>
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={saveCreds}
          loading={configure.isPending}
          disabled={isIproyal ? !apiToken.trim() : !(username.trim() && password.trim())}
        >
          {t('prov.save')}
        </Button>

        <div className="space-y-3 border-t border-line pt-4">
          <p className="font-display text-[13px] font-semibold text-ink">{t('prov.generate')}</p>
          <div className="grid grid-cols-3 gap-3">
            <Field label={t('prov.count')}>
              <Input
                type="number"
                value={count}
                onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value))))}
              />
            </Field>
            <Field label={t('prov.country')}>
              <Input value={country} onChange={(e) => setCountry(e.target.value)} />
            </Field>
            <Field label={t('prov.sessionType')}>
              <Select
                value={sessionType}
                onChange={(e) => setSessionType(e.target.value as 'rotating' | 'sticky')}
                options={[
                  { value: 'rotating', label: t('prov.rotating') },
                  { value: 'sticky', label: t('prov.sticky') },
                ]}
              />
            </Field>
          </div>
          {!provider?.configured && <p className="text-2xs text-ink-faint">{t('prov.needConfig')}</p>}
          <Button
            variant="primary"
            onClick={doGenerate}
            loading={generate.isPending}
            disabled={!provider?.configured}
          >
            <Sparkles className="h-3.5 w-3.5" /> {t('prov.generateBtn')}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
