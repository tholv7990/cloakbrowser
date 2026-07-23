import { useEffect, useState, type FC } from 'react';
import { Controller, useFormContext, useWatch } from 'react-hook-form';
import { AlertTriangle, Plus, RefreshCw, Zap } from 'lucide-react';
import type { Extension, Folder, Proxy, ProxyQuickTest, Tag, WorkflowStatus } from '@/types/api';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { Button } from '@/components/ui/Button';
import { Badge, TagChip } from '@/components/ui/Badge';
import { ProxyHealthDot } from '@/components/domain/StatusBadges';
import { FingerprintGlyph } from '@/components/FingerprintGlyph';
import { ProxyEditorDrawer } from '@/features/proxies/ProxyEditorDrawer';
import { ProxyQuickResult } from '@/features/proxies/ProxyResultViews';
import { useCreateProxy, useQuickTest } from '@/features/proxies/api';
import { parseProxyText } from '@/schemas/proxy';
import type { ProfileWizardValues } from '@/schemas/profile';
import { useT, type TranslationKey } from '@/i18n';

export interface WizardRefs {
  folders: Folder[];
  statuses: WorkflowStatus[];
  tags: Tag[];
  proxies: Proxy[];
  extensions: Extension[];
  browserVersion: string;
  isEdit: boolean;
}

function Warning({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2.5 text-2xs text-warning">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function SelectField({
  name,
  label,
  options,
  hint,
  required,
}: {
  name: keyof ProfileWizardValues;
  label: string;
  options: { value: string; label: string }[];
  hint?: string;
  required?: boolean;
}) {
  const { control, formState } = useFormContext<ProfileWizardValues>();
  const error = formState.errors[name]?.message as string | undefined;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <Field label={label} hint={hint} error={error} required={required}>
          <Select
            options={options}
            value={(field.value as string) ?? ''}
            onChange={(e) => field.onChange(e.target.value)}
            invalid={Boolean(error)}
          />
        </Field>
      )}
    />
  );
}

function ToggleField({
  name,
  label,
  hint,
}: {
  name: keyof ProfileWizardValues;
  label: string;
  hint?: string;
}) {
  const { control } = useFormContext<ProfileWizardValues>();
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <div className="flex items-start justify-between gap-4 rounded-md border border-line bg-surface-sunken px-3 py-2.5">
          <div>
            <p className="text-[13px] font-medium text-ink">{label}</p>
            {hint && <p className="text-2xs text-ink-faint">{hint}</p>}
          </div>
          <Toggle checked={Boolean(field.value)} onChange={field.onChange} label={label} />
        </div>
      )}
    />
  );
}

// --- Step 1: General ---------------------------------------------------------

const GeneralStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const t = useT();
  const { register, control, formState, watch } = useFormContext<ProfileWizardValues>();
  return (
    <div className="space-y-4">
      <Field
        label={t('editor.name')}
        required
        error={formState.errors.name?.message}
        htmlFor="wiz-name"
      >
        <Input
          id="wiz-name"
          placeholder="e.g. marketplace-us-01"
          {...register('name')}
          invalid={Boolean(formState.errors.name)}
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="folder_id"
          label={t('editor.folder')}
          options={[
            { value: '', label: t('common.unfiled') },
            ...refs.folders.map((f) => ({ value: f.id, label: f.name })),
          ]}
        />
        <SelectField
          name="workflow_status_id"
          label={t('editor.workflowStatus')}
          options={[
            { value: '', label: t('editor.noStatus') },
            ...refs.statuses.map((s) => ({ value: s.id, label: s.name })),
          ]}
        />
      </div>
      <Controller
        control={control}
        name="tag_ids"
        render={({ field }) => (
          <Field label={t('editor.tags')}>
            <div className="flex flex-wrap gap-1.5">
              {refs.tags.map((tag) => {
                const active = field.value.includes(tag.id);
                return (
                  <button
                    key={tag.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      field.onChange(
                        active
                          ? field.value.filter((id) => id !== tag.id)
                          : [...field.value, tag.id],
                      )
                    }
                    className={active ? 'opacity-100' : 'opacity-45 hover:opacity-80'}
                  >
                    <TagChip name={tag.name} color={tag.color} />
                  </button>
                );
              })}
              {refs.tags.length === 0 && (
                <span className="text-2xs text-ink-faint">{t('editor.noTags')}</span>
              )}
            </div>
          </Field>
        )}
      />
      <Field
        label={t('editor.notes')}
        hint={`${watch('notes')?.length ?? 0} / 4,000`}
        error={formState.errors.notes?.message}
      >
        <Textarea rows={3} placeholder={t('editor.notesPlaceholder')} {...register('notes')} />
      </Field>
      <Field
        label={t('editor.startupUrls')}
        hint={t('editor.startupUrlsHint')}
        error={formState.errors.startup_urls_text?.message}
      >
        <Textarea
          rows={3}
          placeholder={'https://example.com'}
          {...register('startup_urls_text')}
          className="font-mono text-[12px]"
        />
      </Field>
      <p className="text-2xs text-ink-faint">{t('editor.noCredsNote')}</p>
    </div>
  );
};

// --- Step 2: Proxy and location ---------------------------------------------

const ProxyLocationStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const t = useT();
  const { register, formState, setValue } = useFormContext<ProfileWizardValues>();
  const proxyId = useWatch<ProfileWizardValues>({ name: 'proxy_id' }) as string;
  const geoMode = useWatch<ProfileWizardValues>({ name: 'geolocation_mode' }) as string;
  const profileName = useWatch<ProfileWizardValues>({ name: 'name' }) as string;
  const selected = refs.proxies.find((p) => p.id === proxyId) ?? null;
  const [proxyEditorOpen, setProxyEditorOpen] = useState(false);
  const [pasteProxy, setPasteProxy] = useState('');
  const [pasteError, setPasteError] = useState<string | null>(null);
  const [checkResult, setCheckResult] = useState<ProxyQuickTest | null>(null);
  const createProxy = useCreateProxy();
  const quickTest = useQuickTest();

  // Clear a stale check result when the selected proxy changes.
  useEffect(() => setCheckResult(null), [proxyId]);

  const checkProxy = async () => {
    if (!proxyId) return;
    setCheckResult(null);
    try {
      setCheckResult(await quickTest.mutateAsync(proxyId));
    } catch {
      // Failures surface as ok:false in the result; nothing else to do here.
    }
  };

  const quickAddProxy = async () => {
    const parsed = parseProxyText(pasteProxy);
    if (!parsed || !parsed.host || !parsed.port) {
      setPasteError(t('editor.quickProxyInvalid'));
      return;
    }
    try {
      const created = await createProxy.mutateAsync({
        label: profileName?.trim() || parsed.host,
        scheme: parsed.scheme ?? 'http',
        host: parsed.host,
        port: Number(parsed.port),
        username: parsed.username || null,
        password: parsed.password || undefined,
        test_before_launch: true,
      });
      setValue('proxy_id', created.id, { shouldValidate: true });
      setPasteProxy('');
      setPasteError(null);
    } catch {
      setPasteError(t('editor.quickProxyFailed'));
    }
  };

  return (
    <div className="space-y-4">
      <Field
        label={t('editor.quickProxy')}
        hint={t('editor.quickProxyHint')}
        error={pasteError ?? undefined}
      >
        <div className="flex gap-2">
          <Input
            value={pasteProxy}
            onChange={(e) => {
              setPasteProxy(e.target.value);
              setPasteError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                quickAddProxy();
              }
            }}
            placeholder="socks5h://user:pass@host:1080  ·  host:port:user:pass"
            className="font-mono text-[12px]"
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={quickAddProxy}
            loading={createProxy.isPending}
            disabled={!pasteProxy.trim()}
          >
            <Plus className="h-3.5 w-3.5" /> {t('editor.quickProxyAdd')}
          </Button>
        </div>
      </Field>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setProxyEditorOpen(true)}
        >
          <Plus className="h-3.5 w-3.5" /> {t('editor.advancedProxy')}
        </Button>
        {!selected && <span className="text-2xs text-ink-faint">{t('editor.directNoProxy')}</span>}
      </div>
      <ProxyEditorDrawer
        open={proxyEditorOpen}
        proxy={null}
        defaultLabel={profileName}
        onClose={() => setProxyEditorOpen(false)}
        onSaved={(saved) => setValue('proxy_id', saved.id, { shouldValidate: true })}
      />
      {selected && (
        <div className="space-y-2 rounded-md border border-line bg-surface-sunken p-3 text-[13px]">
          <div className="flex items-center justify-between gap-2">
            <span className="data text-ink">{selected.masked_endpoint}</span>
            <div className="flex items-center gap-2">
              <ProxyHealthDot
                health={
                  selected.reputation === 'malicious'
                    ? 'unreachable'
                    : selected.reputation === 'suspicious'
                      ? 'degraded'
                      : selected.latency_ms
                        ? 'healthy'
                        : 'untested'
                }
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={checkProxy}
                loading={quickTest.isPending}
              >
                <Zap className="h-3.5 w-3.5" /> {t('editor.checkProxy')}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setValue('proxy_id', '', { shouldValidate: true })}
              >
                {t('common.remove')}
              </Button>
            </div>
          </div>
          {checkResult && <ProxyQuickResult result={checkResult} />}
        </div>
      )}
      <ToggleField
        name="test_proxy_before_launch"
        label={t('editor.testProxy')}
        hint={t('editor.testProxyHint')}
      />
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="geo_mode"
          label={t('editor.geoSource')}
          options={[
            { value: 'proxy', label: t('opt.fromProxy') },
            { value: 'system', label: t('opt.system') },
            { value: 'manual', label: t('opt.manual') },
          ]}
        />
        <SelectField
          name="webrtc_mode"
          label={t('editor.webrtc')}
          options={[
            { value: 'proxy', label: t('opt.proxy') },
            { value: 'direct', label: t('opt.direct') },
            { value: 'disabled', label: t('opt.disabled') },
          ]}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t('editor.locale')} error={formState.errors.locale?.message}>
          <Input placeholder="en-US" {...register('locale')} />
        </Field>
        <Field label={t('editor.timezone')} error={formState.errors.timezone?.message}>
          <Input mono placeholder="America/New_York" {...register('timezone')} />
        </Field>
      </div>
      <SelectField
        name="geolocation_mode"
        label={t('editor.geoPermission')}
        options={[
          { value: 'ask', label: t('opt.ask') },
          { value: 'proxy', label: t('opt.fromProxy') },
          { value: 'manual', label: t('editor.manualCoords') },
          { value: 'block', label: t('opt.block') },
        ]}
      />
      {geoMode === 'manual' && (
        <div className="grid grid-cols-3 gap-4">
          <Field label={t('editor.latitude')} error={formState.errors.latitude?.message}>
            <Input {...register('latitude')} />
          </Field>
          <Field label={t('editor.longitude')} error={formState.errors.longitude?.message}>
            <Input {...register('longitude')} />
          </Field>
          <Field label={t('editor.accuracy')}>
            <Input {...register('accuracy')} />
          </Field>
        </div>
      )}
    </div>
  );
};

// --- Step 3: Browser identity ------------------------------------------------

const IdentityStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const t = useT();
  const { register, setValue, formState } = useFormContext<ProfileWizardValues>();
  const seed = useWatch<ProfileWizardValues>({ name: 'fingerprint_seed' }) as string;
  const versionMode = useWatch<ProfileWizardValues>({ name: 'browser_version_mode' }) as string;
  const uaMode = useWatch<ProfileWizardValues>({ name: 'user_agent_mode' }) as string;
  return (
    <div className="space-y-4">
      <SelectField
        name="fingerprint_preset"
        label={t('editor.fpPreset')}
        hint={t('editor.fpPresetHint')}
        options={[
          { value: 'consistent', label: t('editor.fpConsistent') },
          { value: 'default', label: t('opt.default') },
        ]}
      />
      <Field label={t('editor.fpSeed')} required error={formState.errors.fingerprint_seed?.message}>
        <div className="flex items-center gap-2">
          <FingerprintGlyph seed={seed || '0'} size={34} />
          <Input
            mono
            className="flex-1"
            {...register('fingerprint_seed')}
            invalid={Boolean(formState.errors.fingerprint_seed)}
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() =>
              setValue('fingerprint_seed', String(Math.floor(Math.random() * 2 ** 32)), {
                shouldValidate: true,
              })
            }
          >
            <RefreshCw className="h-3.5 w-3.5" /> {t('common.generate')}
          </Button>
        </div>
      </Field>
      {refs.isEdit && <Warning>{t('editor.fpSeedWarn')}</Warning>}
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="browser_version_mode"
          label={t('editor.browserVersion')}
          hint={t('editor.browserVersionHint')}
          options={[
            { value: 'installed', label: t('editor.installed', { version: refs.browserVersion }) },
            { value: 'pinned', label: t('editor.pinned') },
          ]}
        />
        {versionMode === 'pinned' && (
          <Field
            label={t('editor.pinnedVersion')}
            error={formState.errors.browser_version?.message}
          >
            <Input mono placeholder="146.0.7680.177" {...register('browser_version')} />
          </Field>
        )}
      </div>
      <SelectField
        name="user_agent_mode"
        label={t('editor.userAgent')}
        hint={t('editor.userAgentHint')}
        options={[
          { value: 'automatic', label: t('opt.automatic') },
          { value: 'custom', label: t('editor.customAdvanced') },
        ]}
      />
      {uaMode === 'custom' && (
        <Field
          label={t('editor.customUserAgent')}
          error={formState.errors.custom_user_agent?.message}
        >
          <Textarea rows={2} className="font-mono text-[12px]" {...register('custom_user_agent')} />
        </Field>
      )}
      <p className="text-2xs text-ink-faint">{t('editor.platformNote')}</p>
    </div>
  );
};

// --- Step 4: Window and appearance ------------------------------------------

const WindowStep: FC<{ refs: WizardRefs }> = () => {
  const t = useT();
  const { register, formState } = useFormContext<ProfileWizardValues>();
  const mode = useWatch<ProfileWizardValues>({ name: 'window_mode' }) as string;
  return (
    <div className="space-y-4">
      <SelectField
        name="window_mode"
        label={t('editor.windowMode')}
        options={[
          { value: 'maximized', label: t('editor.maximizedRec') },
          { value: 'custom', label: t('editor.customSize') },
        ]}
      />
      {mode === 'custom' && (
        <div className="grid grid-cols-2 gap-4">
          <Field label={t('editor.width')} error={formState.errors.window_width?.message}>
            <Input {...register('window_width')} placeholder="1920" />
          </Field>
          <Field label={t('editor.height')} error={formState.errors.window_height?.message}>
            <Input {...register('window_height')} placeholder="1080" />
          </Field>
        </div>
      )}
      <SelectField
        name="color_scheme"
        label={t('editor.colorScheme')}
        options={[
          { value: 'system', label: t('opt.system') },
          { value: 'light', label: t('opt.light') },
          { value: 'dark', label: t('opt.dark') },
        ]}
      />
      <p className="text-2xs text-ink-faint">{t('editor.windowNote')}</p>
    </div>
  );
};

// --- Step 5: Cookies and storage --------------------------------------------

const CookiesStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const t = useT();
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-ink-muted">{t('editor.cookiesNote')}</p>
      <div className="rounded-md border border-line bg-surface-sunken p-3 text-2xs text-ink-muted">
        {refs.isEdit ? t('editor.cookiesEdit') : t('editor.cookiesNew')}
      </div>
    </div>
  );
};

// --- Step 6: Extensions ------------------------------------------------------

const ExtensionsStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const t = useT();
  const { control } = useFormContext<ProfileWizardValues>();
  return (
    <div className="space-y-3">
      {refs.isEdit && <Warning>{t('editor.extensionAssignmentUnavailable')}</Warning>}
      <Controller
        control={control}
        name="extension_ids"
        render={({ field }) => (
          <div className="space-y-2">
            {refs.extensions.length === 0 && (
              <p className="text-2xs text-ink-faint">{t('editor.noExtensions')}</p>
            )}
            {refs.extensions.map((ext) => {
              const active = field.value.includes(ext.id);
              return (
                <label
                  key={ext.id}
                  className="flex cursor-pointer items-center justify-between gap-3 rounded-md border border-line bg-surface-sunken px-3 py-2"
                >
                  <div>
                    <p className="text-[13px] text-ink">{ext.name}</p>
                    <p className="data text-2xs text-ink-faint">{ext.directory}</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() =>
                      field.onChange(
                        active
                          ? field.value.filter((id) => id !== ext.id)
                          : [...field.value, ext.id],
                      )
                    }
                    className="h-4 w-4 accent-[rgb(var(--cb-accent))]"
                  />
                </label>
              );
            })}
          </div>
        )}
      />
      <Warning>{t('editor.extWarn')}</Warning>
    </div>
  );
};

// --- Step 7: Advanced behavior ----------------------------------------------

const AdvancedStep: FC<{ refs: WizardRefs }> = () => {
  const t = useT();
  const { register, formState } = useFormContext<ProfileWizardValues>();
  const downloadMode = useWatch<ProfileWizardValues>({ name: 'download_directory_mode' }) as string;
  const hwMode = useWatch<ProfileWizardValues>({ name: 'hardware_concurrency_mode' }) as string;
  const gpuMode = useWatch<ProfileWizardValues>({ name: 'gpu_mode' }) as string;
  const permissionOptions = [
    { value: 'ask', label: t('opt.ask') },
    { value: 'allow', label: t('opt.allow') },
    { value: 'block', label: t('opt.block') },
  ];
  const permissions: { name: keyof ProfileWizardValues; label: string }[] = [
    { name: 'permission_geolocation', label: t('editor.perm.geolocation') },
    { name: 'permission_notifications', label: t('editor.perm.notifications') },
    { name: 'permission_camera', label: t('editor.perm.camera') },
    { name: 'permission_microphone', label: t('editor.perm.microphone') },
    { name: 'permission_clipboard', label: t('editor.perm.clipboard') },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <ToggleField
          name="humanize_enabled"
          label={t('editor.humanize')}
          hint={t('editor.humanizeHint')}
        />
        <SelectField
          name="humanize_preset"
          label={t('editor.humanizePreset')}
          options={[
            { value: 'default', label: t('opt.default') },
            { value: 'careful', label: t('opt.careful') },
          ]}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ToggleField name="clear_cache_before_launch" label={t('editor.clearCache')} />
        <ToggleField name="restore_previous_tabs" label={t('editor.restoreTabs')} />
      </div>
      <SelectField
        name="download_directory_mode"
        label={t('editor.downloads')}
        options={[
          { value: 'profile', label: t('editor.profileDownloadDir') },
          { value: 'custom', label: t('editor.customDir') },
        ]}
      />
      {downloadMode === 'custom' && (
        <Field
          label={t('editor.customDownloadDir')}
          error={formState.errors.custom_download_directory?.message}
        >
          <Input
            mono
            placeholder="C:\\Downloads\\profile"
            {...register('custom_download_directory')}
          />
        </Field>
      )}
      <Field label={t('editor.browserPermissions')}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {permissions.map((permission) => (
            <label key={permission.name} className="flex flex-col gap-1">
              <span className="text-2xs text-ink-muted">{permission.label}</span>
              <Select {...register(permission.name)} options={permissionOptions} />
            </label>
          ))}
        </div>
      </Field>
      <ToggleField
        name="ignore_https_errors"
        label={t('editor.ignoreHttps')}
        hint={t('editor.ignoreHttpsHint')}
      />
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="hardware_concurrency_mode"
          label={t('editor.hwConcurrency')}
          options={[
            { value: 'automatic', label: t('opt.automatic') },
            { value: 'custom', label: t('opt.custom') },
          ]}
        />
        {hwMode === 'custom' && (
          <Field label={t('editor.cores')} error={formState.errors.hardware_concurrency?.message}>
            <Input {...register('hardware_concurrency')} placeholder="12" />
          </Field>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="gpu_mode"
          label={t('editor.gpu')}
          options={[
            { value: 'automatic', label: t('opt.automatic') },
            { value: 'custom_vendor', label: t('editor.customVendor') },
          ]}
        />
        {gpuMode === 'custom_vendor' && (
          <Field label={t('editor.gpuVendor')} error={formState.errors.gpu_vendor?.message}>
            <Input {...register('gpu_vendor')} placeholder="Google Inc. (Intel)" />
          </Field>
        )}
      </div>
      <Field
        label={t('editor.additionalArgs')}
        hint={t('editor.additionalArgsHint')}
        error={formState.errors.additional_args?.message}
      >
        <Input mono placeholder="--disable-features=Foo" {...register('additional_args')} />
      </Field>
      <p className="text-2xs text-ink-faint">{t('editor.headedNote')}</p>
    </div>
  );
};

// --- Step 8: Review ----------------------------------------------------------

const ReviewStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const t = useT();
  const values = useWatch<ProfileWizardValues>() as ProfileWizardValues;
  const proxy = refs.proxies.find((p) => p.id === values.proxy_id);
  const urls = values.startup_urls_text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const rows: [string, string][] = [
    [t('editor.review.name'), values.name || '—'],
    [t('editor.review.fpPreset'), values.fingerprint_preset],
    [t('editor.review.fpSeed'), values.fingerprint_seed],
    [
      t('editor.review.browser'),
      values.browser_version_mode === 'pinned'
        ? t('editor.review.pinnedVersion', { version: values.browser_version })
        : t('editor.installed', { version: refs.browserVersion }),
    ],
    [t('editor.review.localeTz'), `${values.locale || '—'} · ${values.timezone || '—'}`],
    [
      t('editor.review.proxy'),
      proxy ? `${proxy.label} (${proxy.masked_endpoint})` : t('editor.review.directConnection'),
    ],
    [
      t('editor.review.window'),
      values.window_mode === 'custom'
        ? `${values.window_width}×${values.window_height}`
        : t('editor.review.maximized'),
    ],
    [t('editor.review.startupUrls'), urls.length ? `${urls.length}` : t('editor.review.none')],
  ];
  const warnings: string[] = [];
  if (values.geo_mode === 'proxy' && !values.proxy_id) warnings.push(t('editor.warn.geoNoProxy'));
  if (proxy && proxy.reputation === 'malicious') warnings.push(t('editor.warn.maliciousProxy'));
  if (proxy && proxy.assigned_profile_count > (refs.isEdit ? 1 : 0))
    warnings.push(t('editor.warn.sharedProxy'));
  if (values.ignore_https_errors) warnings.push(t('editor.warn.ignoreHttps'));
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <FingerprintGlyph seed={values.fingerprint_seed || '0'} size={40} />
        <div>
          <p className="font-display text-base font-semibold text-ink">
            {values.name || t('editor.untitled')}
          </p>
          <p className="text-2xs text-ink-faint">{t('editor.reviewBeforeSaving')}</p>
        </div>
      </div>
      <dl className="divide-y divide-line rounded-md border border-line">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start justify-between gap-4 px-3 py-2">
            <dt className="text-2xs uppercase tracking-wide text-ink-faint">{label}</dt>
            <dd className="max-w-[60%] truncate text-right text-[13px] text-ink" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
      {warnings.length > 0 && (
        <div className="space-y-2">
          {warnings.map((warning) => (
            <Warning key={warning}>{warning}</Warning>
          ))}
        </div>
      )}
    </div>
  );
};

export interface WizardStep {
  id: string;
  titleKey: TranslationKey;
  descKey: TranslationKey;
  Component: FC<{ refs: WizardRefs }>;
}

export const WIZARD_STEPS: WizardStep[] = [
  {
    id: 'general',
    titleKey: 'editor.step.general',
    descKey: 'editor.step.general.desc',
    Component: GeneralStep,
  },
  {
    id: 'proxy-location',
    titleKey: 'editor.step.proxyLocation',
    descKey: 'editor.step.proxyLocation.desc',
    Component: ProxyLocationStep,
  },
  {
    id: 'identity',
    titleKey: 'editor.step.identity',
    descKey: 'editor.step.identity.desc',
    Component: IdentityStep,
  },
  {
    id: 'window',
    titleKey: 'editor.step.window',
    descKey: 'editor.step.window.desc',
    Component: WindowStep,
  },
  {
    id: 'cookies',
    titleKey: 'editor.step.cookies',
    descKey: 'editor.step.cookies.desc',
    Component: CookiesStep,
  },
  {
    id: 'extensions',
    titleKey: 'editor.step.extensions',
    descKey: 'editor.step.extensions.desc',
    Component: ExtensionsStep,
  },
  {
    id: 'advanced',
    titleKey: 'editor.step.advanced',
    descKey: 'editor.step.advanced.desc',
    Component: AdvancedStep,
  },
  {
    id: 'review',
    titleKey: 'editor.step.review',
    descKey: 'editor.step.review.desc',
    Component: ReviewStep,
  },
];
