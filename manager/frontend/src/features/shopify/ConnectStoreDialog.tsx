import { useEffect, useState } from 'react';
import { Modal } from '@/components/ui/Modal';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Button } from '@/components/ui/Button';
import { useT } from '@/i18n';
import { useProxies } from '@/features/proxies/api';
import { useConnectStore } from './api';

export function ConnectStoreDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const connect = useConnectStore();
  const proxies = useProxies();

  const [label, setLabel] = useState('');
  const [shopDomain, setShopDomain] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [proxyId, setProxyId] = useState('');

  useEffect(() => {
    if (open) {
      setLabel('');
      setShopDomain('');
      setClientId('');
      setClientSecret('');
      setProxyId('');
    }
  }, [open]);

  const proxyOptions = [
    { value: '', label: t('shop.connect.proxyNone') },
    ...(proxies.data ?? []).map((proxy) => ({ value: proxy.id, label: proxy.label })),
  ];

  const submit = () => {
    connect.mutate(
      {
        label,
        shop_domain: shopDomain,
        client_id: clientId,
        client_secret: clientSecret,
        proxy_id: proxyId || null,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('shop.connect.title')}
      description={t('shop.connect.desc')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={connect.isPending}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" onClick={submit} loading={connect.isPending}>
            {t('shop.connect.submit')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label={t('shop.connect.label')}>
          <Input value={label} onChange={(event) => setLabel(event.target.value)} />
        </Field>
        <Field label={t('shop.connect.domain')}>
          <Input
            value={shopDomain}
            onChange={(event) => setShopDomain(event.target.value)}
            placeholder="store.myshopify.com"
          />
        </Field>
        <Field label={t('shop.connect.clientId')}>
          <Input value={clientId} onChange={(event) => setClientId(event.target.value)} />
        </Field>
        <Field label={t('shop.connect.clientSecret')}>
          <Input
            type="password"
            value={clientSecret}
            onChange={(event) => setClientSecret(event.target.value)}
          />
        </Field>
        <Field label={t('shop.connect.proxy')}>
          <Select
            value={proxyId}
            onChange={(event) => setProxyId(event.target.value)}
            options={proxyOptions}
          />
        </Field>
      </div>
    </Modal>
  );
}
