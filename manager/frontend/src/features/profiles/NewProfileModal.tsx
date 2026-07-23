import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Settings2, Sparkles, XCircle, Zap } from 'lucide-react';
import type { Folder, ProxyProviderId, ProxyQuickTest, ProxyScheme } from '@/types/api';
import { api } from '@/api';
import { useT } from '@/i18n';
import { useToast } from '@/components/ui/Toast';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Badge } from '@/components/ui/Badge';
import { countryFlag, formatLatency } from '@/lib/format';
import { defaultWizardValues, wizardValuesToPayload } from '@/schemas/profile';
import { parseProxyText, proxySchemes } from '@/schemas/proxy';
import { useProxyProviders, useQuickTestAdhoc } from '@/features/proxies/api';
import { ProvidersDialog } from '@/features/proxies/ProvidersDialog';
import { listTemplates } from '@/features/profile-editor/profileTemplates';

type ProxyMode = 'none' | 'one' | 'list' | 'provider';

/** Structured single-proxy value for the inline form (port/creds as strings). */
interface OneProxy {
  scheme: ProxyScheme;
  host: string;
  port: string;
  username: string;
  password: string;
}

const emptyOneProxy: OneProxy = { scheme: 'http', host: '', port: '', username: '', password: '' };

// Selectable proxy transports (drop "direct" — that's the "None" mode).
const schemeOptions = proxySchemes
  .filter((s) => s !== 'direct')
  .map((s) => ({ value: s, label: s.toUpperCase() }));

/**
 * One create flow that scales from a single profile to a batch (BitBrowser /
 * Hidemium style): Count = 1 makes one; Count > 1 makes N named `<pattern> NN`.
 * A pasted proxy list is assigned one-per-profile. Everything else uses the
 * no-leak defaults (or the chosen template); the full wizard is one click away.
 */
export function NewProfileModal({
  open,
  onClose,
  folders,
}: {
  open: boolean;
  onClose: () => void;
  folders: Folder[];
}) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const templates = useMemo(() => (open ? listTemplates() : []), [open]);

  const [name, setName] = useState('');
  const [count, setCount] = useState(1);
  const [folderId, setFolderId] = useState('');
  const [proxyMode, setProxyMode] = useState<ProxyMode>('none');
  const [proxyText, setProxyText] = useState('');
  const [proxyOne, setProxyOne] = useState<OneProxy>(emptyOneProxy);
  const [templateId, setTemplateId] = useState('builtin:no-leak');
  const [providerId, setProviderId] = useState<ProxyProviderId>('iproyal');
  const [country, setCountry] = useState('US');
  const [providersOpen, setProvidersOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  const providers = useProxyProviders();
  const provider = (providers.data ?? []).find((p) => p.id === providerId);

  useEffect(() => {
    if (!open) return;
    setName('');
    setCount(1);
    setFolderId('');
    setProxyMode('none');
    setProxyText('');
    setProxyOne(emptyOneProxy);
    setTemplateId('builtin:no-leak');
    setProviderId('iproyal');
    setCountry('US');
    setBusy(false);
    setDone(0);
  }, [open]);

  const proxyLines = proxyText
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  // Drop any seed a (legacy) template may carry — defaultWizardValues() runs per
  // profile below, so each gets its own fresh, unique fingerprint seed.
  const { fingerprint_seed: _dropSeed, ...templateConfig } =
    templates.find((tpl) => tpl.id === templateId)?.config ?? {};

  const proxySpecForIndex = (
    i: number,
  ): { scheme: ProxyScheme; host: string; port: number; username: string; password: string } | null => {
    if (proxyMode === 'one') {
      const host = proxyOne.host.trim();
      const port = Number(proxyOne.port);
      if (!host || !port) return null;
      return { scheme: proxyOne.scheme, host, port, username: proxyOne.username.trim(), password: proxyOne.password };
    }
    if (proxyMode === 'list') {
      const parsed = proxyLines[i] ? parseProxyText(proxyLines[i]) : null;
      if (!parsed?.host || !parsed.port) return null;
      return {
        scheme: parsed.scheme ?? 'http',
        host: parsed.host,
        port: Number(parsed.port),
        username: parsed.username,
        password: parsed.password,
      };
    }
    return null;
  };

  const shortfall = proxyMode === 'list' && proxyLines.length > 0 && proxyLines.length < count;

  const nameFor = (i: number): string => {
    const base = name.trim();
    if (count === 1) return base || `profile-${Math.floor(Math.random() * 9000) + 1000}`;
    return `${base || 'Profile'} ${String(i + 1).padStart(2, '0')}`;
  };

  const create = async () => {
    setBusy(true);
    setDone(0);
    let ok = 0;
    try {
      // Provider mode: generate `count` proxies from the provider up front, then
      // hand one to each profile.
      let providerIds: string[] = [];
      if (proxyMode === 'provider') {
        try {
          const result = await api.generateProxies({
            provider: providerId,
            count,
            country: country.trim() || 'US',
            session_type: 'sticky',
          });
          providerIds = result.proxy_ids;
        } catch (error) {
          toast({
            title: t('new.providerFailed'),
            description: (error as Error).message,
            tone: 'danger',
          });
          setBusy(false);
          return;
        }
      }
      for (let i = 0; i < count; i++) {
        const profileName = nameFor(i);
        let proxyId = '';
        if (proxyMode === 'provider') {
          proxyId = providerIds[i] ?? '';
        } else {
          // 'one' uses the structured form (its chosen scheme); 'list' parses the
          // i-th pasted line (scheme:// prefix honoured, else defaults to http).
          const spec = proxySpecForIndex(i);
          if (spec) {
            try {
              const proxy = await api.createProxy({
                label: profileName,
                scheme: spec.scheme,
                host: spec.host,
                port: spec.port,
                username: spec.username || null,
                password: spec.password || undefined,
                test_before_launch: true,
              });
              proxyId = proxy.id;
            } catch {
              // Proxy creation failed — still create the profile, just direct.
            }
          }
        }
        const values = defaultWizardValues({
          ...templateConfig,
          name: profileName,
          folder_id: folderId,
          proxy_id: proxyId,
        });
        try {
          await api.createProfile(wizardValuesToPayload(values));
          ok += 1;
        } catch {
          // Skip a single failure; report the shortfall at the end.
        }
        setDone(i + 1);
      }
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      toast({
        title:
          ok === count
            ? t('new.created', { count: ok })
            : t('new.createdPartial', { ok, total: count }),
        tone: ok === count ? 'success' : 'warning',
      });
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const openAdvanced = () => {
    onClose();
    navigate('/profiles/new');
  };

  return (
    <>
    <Modal
      open={open}
      onClose={onClose}
      title={t('new.title')}
      description={t('new.desc')}
      footer={
        <>
          <Button variant="ghost" onClick={openAdvanced} disabled={busy}>
            {t('new.advanced')}
          </Button>
          <Button variant="primary" onClick={create} loading={busy}>
            {busy && count > 1 ? `${done}/${count}` : t(count > 1 ? 'new.createN' : 'new.createOne')}
          </Button>
        </>
      }
    >
      <div className="space-y-3.5">
        <div className="grid grid-cols-[1fr_100px] gap-3">
          <Field label={t('new.namePattern')} hint={t('new.namePatternHint')}>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={count > 1 ? 'Marketplace' : 'e.g. Marketplace US'}
              autoFocus
            />
          </Field>
          <Field label={t('new.count')}>
            <Input
              type="number"
              min={1}
              max={100}
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
              mono
            />
          </Field>
        </div>

        <Field label={t('editor.folder')}>
          <Select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            options={[
              { value: '', label: t('dlg.moveFolder.unfiled') },
              ...folders.map((f) => ({ value: f.id, label: f.name })),
            ]}
          />
        </Field>

        <Field label={t('new.proxy')} hint={proxyMode === 'list' ? t('new.proxyListHint') : undefined}>
          <Select
            value={proxyMode}
            onChange={(e) => setProxyMode(e.target.value as ProxyMode)}
            options={[
              { value: 'none', label: t('new.proxyNone') },
              { value: 'one', label: t('new.proxyOne') },
              { value: 'list', label: t('new.proxyList') },
              { value: 'provider', label: t('new.proxyProvider') },
            ]}
          />
        </Field>
        {proxyMode === 'provider' && (
          <div className="space-y-2 rounded-md border border-line bg-surface-sunken p-3">
            <div className="grid grid-cols-[1fr_120px] gap-2">
              <Field label={t('new.provider')}>
                <Select
                  value={providerId}
                  onChange={(e) => setProviderId(e.target.value as ProxyProviderId)}
                  options={(providers.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
                />
              </Field>
              <Field label={t('new.providerCountry')}>
                <Input
                  value={country}
                  onChange={(e) => setCountry(e.target.value.toUpperCase().slice(0, 2))}
                  placeholder="US"
                  className="uppercase"
                />
              </Field>
            </div>
            <div className="flex items-center justify-between gap-2">
              <Badge tone={provider?.configured ? 'success' : 'warning'}>
                {provider?.configured ? t('prov.configured') : t('prov.notConfigured')}
              </Badge>
              <Button type="button" variant="ghost" size="sm" onClick={() => setProvidersOpen(true)}>
                <Settings2 className="h-3.5 w-3.5" /> {t('new.providerConfigure')}
              </Button>
            </div>
            <p className="text-2xs text-ink-faint">{t('new.providerHint', { count })}</p>
          </div>
        )}
        {proxyMode === 'one' && <ProxyOneForm value={proxyOne} onChange={setProxyOne} />}
        {proxyMode === 'list' && (
          <>
            <Textarea
              rows={Math.min(6, Math.max(3, count))}
              value={proxyText}
              onChange={(e) => setProxyText(e.target.value)}
              placeholder={'host:port:user:pass\nhost:port:user:pass'}
              className="font-mono text-[12px]"
            />
            <p className="text-2xs text-ink-faint">
              {t('new.proxyCount', { have: proxyLines.length, want: count })}
              {shortfall && ` · ${t('new.proxyShortfall')}`}
            </p>
          </>
        )}

        {templates.length > 0 && (
          <Field label={t('editor.tpl.choose')}>
            <Select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              options={templates.map((tpl) => ({ value: tpl.id, label: tpl.name }))}
            />
          </Field>
        )}

        <p className="flex items-center gap-1.5 text-2xs text-ink-faint">
          <Sparkles className="h-3.5 w-3.5 text-accent" /> {t('new.defaultsNote')}
        </p>
      </div>
    </Modal>
    <ProvidersDialog open={providersOpen} onClose={() => setProvidersOpen(false)} />
    </>
  );
}

/**
 * Inline single-proxy form (BitBrowser style): pick the transport, fill
 * host/port/creds — or paste a full `host:port:user:pass` line into Host to
 * auto-split — and Check it before creating. The chosen scheme is what actually
 * gets saved, so a SOCKS5 proxy is tested and launched as SOCKS5 (not http).
 */
function ProxyOneForm({ value, onChange }: { value: OneProxy; onChange: (v: OneProxy) => void }) {
  const t = useT();
  const test = useQuickTestAdhoc();
  const [result, setResult] = useState<ProxyQuickTest | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set = (patch: Partial<OneProxy>) => onChange({ ...value, ...patch });

  const onHost = (raw: string) => {
    const parsed = parseProxyText(raw);
    if (parsed?.host && parsed.port) {
      onChange({
        scheme: parsed.scheme ?? value.scheme,
        host: parsed.host,
        port: parsed.port,
        username: parsed.username,
        password: parsed.password,
      });
    } else {
      set({ host: raw });
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
      <div className="grid grid-cols-[110px_1fr_88px] gap-2">
        <Field label={t('new.proxyType')}>
          <Select
            value={value.scheme}
            onChange={(e) => set({ scheme: e.target.value as ProxyScheme })}
            options={schemeOptions}
          />
        </Field>
        <Field label={t('pxd.host')}>
          <Input
            value={value.host}
            onChange={(e) => onHost(e.target.value)}
            placeholder="host or host:port:user:pass"
            className="font-mono text-[12px]"
          />
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
          <Input
            type="password"
            value={value.password}
            onChange={(e) => set({ password: e.target.value })}
            autoComplete="new-password"
          />
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
      {result && <OneProxyResult result={result} />}
    </div>
  );
}

/** Compact one-line result for the inline check (IP · flag country · latency). */
function OneProxyResult({ result }: { result: ProxyQuickTest }) {
  const t = useT();
  if (!result.ok) {
    return (
      <p className="flex items-center gap-1.5 text-2xs text-danger">
        <XCircle className="h-3.5 w-3.5" /> {t('new.proxyUnreachable')}
        {result.error ? ` · ${result.error}` : ''}
      </p>
    );
  }
  const flag = countryFlag(result.country);
  const place = [result.city, result.country_name ?? result.country].filter(Boolean).join(', ');
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-success/30 bg-success/10 px-2.5 py-2 text-2xs">
      <span className="flex items-center gap-1 font-medium text-success">
        <CheckCircle2 className="h-3.5 w-3.5" /> {t('new.proxyReachable')}
      </span>
      {result.exit_ip && <span className="data text-ink">{result.exit_ip}</span>}
      {place && (
        <span className="text-ink-muted">
          {flag ? `${flag} ` : ''}
          {place}
        </span>
      )}
      <span className="ml-auto text-ink-faint">{t('pxr.median', { latency: formatLatency(result.latency_ms) })}</span>
    </div>
  );
}
