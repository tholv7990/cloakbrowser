import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Gauge, Zap } from 'lucide-react';
import type { Proxy, ProxyQualityReport, ProxyQuickTest } from '@/types/api';
import { Drawer } from '@/components/ui/Drawer';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { useT } from '@/i18n';
import {
  parseProxyText,
  proxyFormSchema,
  proxySchemes,
  toProxyPayload,
  type ProxyFormValues,
} from '@/schemas/proxy';
import { useCreateProxy, useQualityTest, useQuickTest, useUpdateProxy } from './api';
import { ProxyQualityReportView, ProxyQuickResult } from './ProxyResultViews';
import { ProxyTestProgress } from './ProxyTestProgress';

function defaults(proxy: Proxy | null, defaultLabel = ''): ProxyFormValues {
  return {
    label: proxy?.label ?? defaultLabel,
    scheme: proxy?.scheme ?? 'http',
    host: proxy?.host ?? '',
    port: proxy?.port ?? '',
    username: proxy?.username ?? '',
    password: '',
    test_before_launch: proxy?.test_before_launch ?? true,
  };
}

export function ProxyEditorDrawer({
  open,
  proxy,
  onClose,
  onSaved,
  onRemove,
  defaultLabel = '',
}: {
  open: boolean;
  proxy: Proxy | null;
  onClose: () => void;
  onSaved?: (proxy: Proxy) => void;
  /** When set, shows a "Remove proxy" action (e.g. set a profile back to
   *  direct/no-proxy) in the footer. */
  onRemove?: () => void;
  /** Pre-fill the label for a NEW proxy (e.g. the profile's name when adding
   *  a proxy from the profile form). Ignored when editing an existing proxy. */
  defaultLabel?: string;
}) {
  const t = useT();
  const [current, setCurrent] = useState<Proxy | null>(proxy);
  const [parseText, setParseText] = useState('');
  const [quickResult, setQuickResult] = useState<ProxyQuickTest | null>(null);
  const [qualityResult, setQualityResult] = useState<ProxyQualityReport | null>(null);

  const createProxy = useCreateProxy();
  const updateProxy = useUpdateProxy();
  const quickTest = useQuickTest();
  const qualityTest = useQualityTest();

  const form = useForm<ProxyFormValues>({
    resolver: zodResolver(proxyFormSchema),
    defaultValues: defaults(proxy, defaultLabel),
    mode: 'onChange',
  });
  const { register, handleSubmit, reset, watch, setValue, formState } = form;
  const scheme = watch('scheme');
  const isDirect = scheme === 'direct';
  const schemeOptions = proxySchemes.map((scheme) => ({
    value: scheme,
    label: scheme === 'direct' ? t('pxd.directNoProxy') : scheme.toUpperCase(),
  }));

  useEffect(() => {
    if (open) {
      setCurrent(proxy);
      // defaultLabel is read at open time (not a dep) so typing the profile name
      // later can't wipe an in-progress proxy edit.
      reset(defaults(proxy, defaultLabel));
      setParseText('');
      setQuickResult(null);
      setQualityResult(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, proxy, reset]);

  // Auto-fill all four fields (incl. password) as the user pastes — no button.
  const applyParse = (text: string) => {
    setParseText(text);
    const parsed = parseProxyText(text);
    if (!parsed) return;
    if (parsed.scheme) setValue('scheme', parsed.scheme, { shouldValidate: true });
    setValue('host', parsed.host, { shouldValidate: true });
    setValue('port', Number(parsed.port), { shouldValidate: true });
    setValue('username', parsed.username, { shouldValidate: true });
    setValue('password', parsed.password, { shouldValidate: true });
  };

  const onSubmit = handleSubmit(async (values) => {
    const payload = toProxyPayload(proxyFormSchema.parse(values));
    const saved = current
      ? await updateProxy.mutateAsync({ id: current.id, payload })
      : await createProxy.mutateAsync(payload);
    setCurrent(saved);
    reset(defaults(saved)); // clears the write-only password field
    onSaved?.(saved);
  });

  const runQuick = async () => {
    if (!current) return;
    setQuickResult(null);
    const result = await quickTest.mutateAsync(current.id);
    setQuickResult(result);
  };
  const runQuality = async () => {
    if (!current) return;
    setQualityResult(null);
    const report = await qualityTest.mutateAsync(current.id);
    setQualityResult(report);
  };

  const saving = createProxy.isPending || updateProxy.isPending;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t(proxy ? 'pxd.edit' : 'proxies.add')}
      description={t('pxd.desc')}
      footer={
        <>
          {onRemove && (
            <Button variant="ghost" className="mr-auto text-danger" onClick={onRemove}>
              {t('pxd.removeProxy')}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button
            variant="primary"
            onClick={onSubmit}
            loading={saving}
            disabled={!formState.isValid}
          >
            {t(current ? 'pxd.save' : 'pxd.create')}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <Field label={t('proxies.col.label')} required error={formState.errors.label?.message}>
          <Input
            placeholder="e.g. US residential — account pool"
            {...register('label')}
            invalid={Boolean(formState.errors.label)}
          />
        </Field>

        <Field label={t('pxd.mode')} required>
          <Select {...register('scheme')} options={schemeOptions} />
        </Field>

        {!isDirect && (
          <>
            <Field label={t('pxd.pasteParse')} hint={t('pxd.parseHint')}>
              <Input
                value={parseText}
                onChange={(e) => applyParse(e.target.value)}
                placeholder="socks5h://user:pass@host:1080"
                className="font-mono text-[12px]"
              />
            </Field>

            <div className="grid grid-cols-[1fr_120px] gap-3">
              <Field label={t('pxd.host')} required error={formState.errors.host?.message}>
                <Input
                  placeholder="proxy.example"
                  {...register('host')}
                  invalid={Boolean(formState.errors.host)}
                  mono
                />
              </Field>
              <Field label={t('pxd.port')} required error={formState.errors.port?.message}>
                <Input
                  type="number"
                  placeholder="1080"
                  {...register('port')}
                  invalid={Boolean(formState.errors.port)}
                  mono
                />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label={t('pxd.username')}>
                <Input autoComplete="off" {...register('username')} />
              </Field>
              <Field
                label={t('auth.password')}
                hint={t(current?.has_password ? 'pxd.pwStored' : 'pxd.pwWriteOnly')}
              >
                <Input
                  type="password"
                  autoComplete="new-password"
                  placeholder={current?.has_password ? '••••••••' : ''}
                  {...register('password')}
                />
              </Field>
            </div>

            {scheme === 'socks5' && (
              <p className="rounded-md border border-warning/30 bg-warning/10 p-2.5 text-2xs text-warning">
                {t('pxd.socks5Warn')}
              </p>
            )}
          </>
        )}

        <div className="flex items-start justify-between gap-4 rounded-md border border-line bg-surface-sunken px-3 py-2.5">
          <div>
            <p className="text-[13px] font-medium text-ink">{t('pxd.testBefore')}</p>
            <p className="text-2xs text-ink-faint">{t('editor.testProxyHint')}</p>
          </div>
          <Toggle
            checked={watch('test_before_launch')}
            onChange={(value) => setValue('test_before_launch', value)}
            label={t('pxd.testToggle')}
          />
        </div>
      </form>

      {!isDirect && (
        <div className="mt-5 space-y-3 border-t border-line pt-4">
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={runQuick}
              disabled={!current}
              loading={quickTest.isPending}
            >
              <Zap className="h-3.5 w-3.5" /> {t('pxd.quickTest')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={runQuality}
              disabled={!current}
              loading={qualityTest.isPending}
            >
              <Gauge className="h-3.5 w-3.5" /> {t('pxd.fullQualityTest')}
            </Button>
          </div>
          {!current && <p className="text-2xs text-ink-faint">{t('pxd.saveToTest')}</p>}
          {current && (
            <>
              <ProxyTestProgress proxyId={current.id} kind="quick" active={quickTest.isPending} />
              <ProxyTestProgress
                proxyId={current.id}
                kind="quality"
                active={qualityTest.isPending}
              />
            </>
          )}
          {quickResult && <ProxyQuickResult result={quickResult} />}
          {qualityResult && <ProxyQualityReportView report={qualityResult} />}
        </div>
      )}
    </Drawer>
  );
}
