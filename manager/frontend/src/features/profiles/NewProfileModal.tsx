import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Settings2, Sparkles } from 'lucide-react';
import type { Folder, Proxy, ProxyProviderId, ProxyScheme } from '@/types/api';
import { api } from '@/api';
import { useT } from '@/i18n';
import { useToast } from '@/components/ui/Toast';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Badge } from '@/components/ui/Badge';
import {
  defaultWizardValues,
  wizardValuesToPayload,
  wizardValuesToValidationDraft,
} from '@/schemas/profile';
import { parseProxyText } from '@/schemas/proxy';
import { useProxies, useProxyProviders } from '@/features/proxies/api';
import { useSettings } from '@/features/settings/api';
import { ProxyEditorDrawer } from '@/features/proxies/ProxyEditorDrawer';
import { ProvidersDialog } from '@/features/proxies/ProvidersDialog';
import { listTemplates } from '@/features/profile-editor/profileTemplates';

type ProxyMode = 'none' | 'one' | 'list' | 'provider';

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
  const [selectedProxy, setSelectedProxy] = useState<Proxy | null>(null);
  const [assignedProxyId, setAssignedProxyId] = useState('');
  const [proxyEditorOpen, setProxyEditorOpen] = useState(false);
  const [templateId, setTemplateId] = useState('builtin:no-leak');
  // '' = use the installed build; otherwise a pinned full version (e.g. 150.x).
  const [browserVersion, setBrowserVersion] = useState('');
  const [providerId, setProviderId] = useState<ProxyProviderId>('iproyal');
  const [country, setCountry] = useState('US');
  const [providersOpen, setProvidersOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  const providers = useProxyProviders();
  const proxies = useProxies();
  const provider = (providers.data ?? []).find((p) => p.id === providerId);

  // Chromium build per profile: the installed one by default, or pin the newer
  // Pro build when the license offers it (seat-capped, so it stays opt-in).
  const settings = useSettings();
  const installedVersion = settings.data?.browser.version ?? '';
  const latestVersion = settings.data?.browser.latest_version ?? '';
  const versionOptions = [
    {
      value: '',
      label: installedVersion
        ? t('new.versionInstalled', { version: installedVersion })
        : t('opt.default'),
    },
    ...(latestVersion && latestVersion !== installedVersion
      ? [{ value: latestVersion, label: t('new.versionLatest', { version: latestVersion }) }]
      : []),
  ];

  useEffect(() => {
    if (!open) return;
    setName('');
    setCount(1);
    setFolderId('');
    setProxyMode('none');
    setProxyText('');
    setSelectedProxy(null);
    setAssignedProxyId('');
    setProxyEditorOpen(false);
    setTemplateId('builtin:no-leak');
    setBrowserVersion('');
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
      const plans = Array.from({ length: count }, (_, i) => {
        const profileName = nameFor(i);
        const values = defaultWizardValues({
          ...templateConfig,
          name: profileName,
          folder_id: folderId,
          proxy_id: proxyMode === 'one' ? assignedProxyId : '',
          browser_version_mode: browserVersion ? 'pinned' : 'installed',
          browser_version: browserVersion,
        });
        return {
          profileName,
          proxySpec: proxySpecForIndex(i),
          payload: wizardValuesToPayload(values),
          validationDraft: wizardValuesToValidationDraft(values),
        };
      });

      // Preflight every independently seeded item before crossing the side-effect
      // boundary. A later invalid/unavailable draft must leave the whole batch
      // safe to retry without duplicate profiles or unattached proxies.
      for (const plan of plans) {
        try {
          const validation = await api.validateProfileDraft(plan.validationDraft);
          if (validation.findings.some((finding) => finding.severity === 'error')) {
            toast({
              title: t('new.validationBlocked'),
              description: t('new.validationErrors'),
              tone: 'danger',
            });
            return;
          }
        } catch {
          toast({
            title: t('new.validationBlocked'),
            description: t('editor.coherence.unavailable'),
            tone: 'danger',
          });
          return;
        }
      }

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
      for (let i = 0; i < plans.length; i++) {
        const plan = plans[i];
        let payload = plan.payload;
        if (proxyMode === 'provider') {
          payload = { ...payload, proxy_id: providerIds[i] ?? null };
        } else if (proxyMode === 'list') {
          // 'list' parses the i-th pasted line (scheme:// prefix honoured, else
          // defaults to http). A selected single proxy is already persisted by
          // ProxyEditorDrawer and remains reusable across profiles.
          const spec = plan.proxySpec;
          if (spec) {
            try {
              const proxy = await api.createProxy({
                label: plan.profileName,
                scheme: spec.scheme,
                host: spec.host,
                port: spec.port,
                username: spec.username || null,
                password: spec.password || undefined,
                test_before_launch: true,
              });
              payload = { ...payload, proxy_id: proxy.id };
            } catch {
              // Proxy creation failed — still create the profile, just direct.
            }
          }
        }
        try {
          await api.createProfile(payload);
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
        {proxyMode === 'one' && (
          <div className="rounded-md border border-line bg-surface-sunken p-3">
            {selectedProxy ? (
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium text-ink">{selectedProxy.label}</p>
                  <p className="truncate font-mono text-2xs text-ink-muted">
                    {selectedProxy.masked_endpoint}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => setProxyEditorOpen(true)}
                  >
                    {t('common.edit')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setSelectedProxy(null);
                      setAssignedProxyId('');
                    }}
                  >
                    {t('common.remove')}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <span className="text-2xs text-ink-faint">{t('editor.directNoProxy')}</span>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setProxyEditorOpen(true)}
                >
                  {t('common.add')}
                </Button>
              </div>
            )}
          </div>
        )}
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

        <Field label={t('editor.browserVersion')} hint={t('new.versionHint')}>
          <Select
            value={browserVersion}
            onChange={(e) => setBrowserVersion(e.target.value)}
            options={versionOptions}
          />
        </Field>

        <p className="flex items-center gap-1.5 text-2xs text-ink-faint">
          <Sparkles className="h-3.5 w-3.5 text-accent" /> {t('new.defaultsNote')}
        </p>
      </div>
    </Modal>
    <ProxyEditorDrawer
      open={proxyEditorOpen}
      proxy={selectedProxy}
      assignableProxies={selectedProxy ? [] : (proxies.data ?? [])}
      defaultLabel={name.trim()}
      onClose={() => setProxyEditorOpen(false)}
      onSaved={(proxy) => {
        setSelectedProxy(proxy);
        setAssignedProxyId(proxy.id);
      }}
      onRemove={
        selectedProxy
          ? () => {
              setSelectedProxy(null);
              setAssignedProxyId('');
              setProxyEditorOpen(false);
            }
          : undefined
      }
    />
    <ProvidersDialog open={providersOpen} onClose={() => setProvidersOpen(false)} />
    </>
  );
}
