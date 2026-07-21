import type { FC } from 'react';
import { Controller, useFormContext, useWatch } from 'react-hook-form';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import type { Extension, Folder, Proxy, Tag, WorkflowStatus } from '@/types/api';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { Button } from '@/components/ui/Button';
import { Badge, TagChip } from '@/components/ui/Badge';
import { ProxyHealthDot } from '@/components/domain/StatusBadges';
import { FingerprintGlyph } from '@/components/FingerprintGlyph';
import type { ProfileWizardValues } from '@/schemas/profile';

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

const PERMISSION_OPTIONS = [
  { value: 'ask', label: 'Ask' },
  { value: 'allow', label: 'Allow' },
  { value: 'block', label: 'Block' },
];

// --- Step 1: General ---------------------------------------------------------

const GeneralStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const { register, control, formState, watch } = useFormContext<ProfileWizardValues>();
  return (
    <div className="space-y-4">
      <Field
        label="Profile name"
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
          label="Folder"
          options={[
            { value: '', label: 'Unfiled' },
            ...refs.folders.map((f) => ({ value: f.id, label: f.name })),
          ]}
        />
        <SelectField
          name="workflow_status_id"
          label="Workflow status"
          options={[
            { value: '', label: 'No status' },
            ...refs.statuses.map((s) => ({ value: s.id, label: s.name })),
          ]}
        />
      </div>
      <Controller
        control={control}
        name="tag_ids"
        render={({ field }) => (
          <Field label="Tags">
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
                <span className="text-2xs text-ink-faint">No tags defined.</span>
              )}
            </div>
          </Field>
        )}
      />
      <Field
        label="Notes"
        hint={`${watch('notes')?.length ?? 0} / 4,000`}
        error={formState.errors.notes?.message}
      >
        <Textarea rows={3} placeholder="Context for this identity…" {...register('notes')} />
      </Field>
      <Field
        label="Startup URLs"
        hint="One per line. http, https, or an approved chrome-extension URL."
        error={formState.errors.startup_urls_text?.message}
      >
        <Textarea
          rows={3}
          placeholder={'https://example.com'}
          {...register('startup_urls_text')}
          className="font-mono text-[12px]"
        />
      </Field>
      <p className="text-2xs text-ink-faint">
        The manager never stores website usernames, passwords, or 2FA secrets. Login state lives in
        the profile&apos;s browser data, not here.
      </p>
    </div>
  );
};

// --- Step 2: Proxy and location ---------------------------------------------

const ProxyLocationStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const { register, formState } = useFormContext<ProfileWizardValues>();
  const proxyId = useWatch<ProfileWizardValues>({ name: 'proxy_id' }) as string;
  const geoMode = useWatch<ProfileWizardValues>({ name: 'geolocation_mode' }) as string;
  const selected = refs.proxies.find((p) => p.id === proxyId) ?? null;
  return (
    <div className="space-y-4">
      <SelectField
        name="proxy_id"
        label="Proxy"
        hint="Reusable proxy records are managed on the Proxies screen."
        options={[
          { value: '', label: 'Direct connection (no proxy)' },
          ...refs.proxies.map((p) => ({ value: p.id, label: `${p.label} · ${p.masked_endpoint}` })),
        ]}
      />
      {selected && (
        <div className="space-y-2 rounded-md border border-line bg-surface-sunken p-3 text-[13px]">
          <div className="flex items-center justify-between">
            <span className="data text-ink">{selected.masked_endpoint}</span>
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
          </div>
          {selected.assigned_profile_count > (refs.isEdit ? 1 : 0) && (
            <Warning>
              This proxy is already assigned to {selected.assigned_profile_count} profile(s).
              Sharing one exit across identities can link them.
            </Warning>
          )}
        </div>
      )}
      <ToggleField
        name="test_proxy_before_launch"
        label="Test proxy before every launch"
        hint="Quick connectivity check before the browser starts."
      />
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="geo_mode"
          label="Geo source"
          options={[
            { value: 'proxy', label: 'From proxy' },
            { value: 'system', label: 'System' },
            { value: 'manual', label: 'Manual' },
          ]}
        />
        <SelectField
          name="webrtc_mode"
          label="WebRTC"
          options={[
            { value: 'proxy', label: 'Proxy' },
            { value: 'direct', label: 'Direct' },
            { value: 'disabled', label: 'Disabled' },
          ]}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Locale" error={formState.errors.locale?.message}>
          <Input placeholder="en-US" {...register('locale')} />
        </Field>
        <Field label="Timezone" error={formState.errors.timezone?.message}>
          <Input mono placeholder="America/New_York" {...register('timezone')} />
        </Field>
      </div>
      <SelectField
        name="geolocation_mode"
        label="Geolocation permission"
        options={[
          { value: 'ask', label: 'Ask' },
          { value: 'proxy', label: 'From proxy' },
          { value: 'manual', label: 'Manual coordinates' },
          { value: 'block', label: 'Block' },
        ]}
      />
      {geoMode === 'manual' && (
        <div className="grid grid-cols-3 gap-4">
          <Field label="Latitude" error={formState.errors.latitude?.message}>
            <Input {...register('latitude')} />
          </Field>
          <Field label="Longitude" error={formState.errors.longitude?.message}>
            <Input {...register('longitude')} />
          </Field>
          <Field label="Accuracy (m)">
            <Input {...register('accuracy')} />
          </Field>
        </div>
      )}
    </div>
  );
};

// --- Step 3: Browser identity ------------------------------------------------

const IdentityStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const { register, setValue, formState } = useFormContext<ProfileWizardValues>();
  const seed = useWatch<ProfileWizardValues>({ name: 'fingerprint_seed' }) as string;
  const versionMode = useWatch<ProfileWizardValues>({ name: 'browser_version_mode' }) as string;
  const uaMode = useWatch<ProfileWizardValues>({ name: 'user_agent_mode' }) as string;
  return (
    <div className="space-y-4">
      <SelectField
        name="fingerprint_preset"
        label="Fingerprint preset"
        hint="Consistent keeps every derived surface coherent across sessions."
        options={[
          { value: 'consistent', label: 'Consistent (recommended)' },
          { value: 'default', label: 'Default' },
        ]}
      />
      <Field label="Fingerprint seed" required error={formState.errors.fingerprint_seed?.message}>
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
            <RefreshCw className="h-3.5 w-3.5" /> Generate
          </Button>
        </div>
      </Field>
      {refs.isEdit && (
        <Warning>
          Generating a new fingerprint changes this profile&apos;s stable identity. Websites may
          recognize it as a new device.
        </Warning>
      )}
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="browser_version_mode"
          label="Browser version"
          options={[
            { value: 'installed', label: `Installed (${refs.browserVersion})` },
            { value: 'pinned', label: 'Pinned' },
          ]}
        />
        {versionMode === 'pinned' && (
          <Field label="Pinned version" error={formState.errors.browser_version?.message}>
            <Input mono placeholder="146.0.7680.177" {...register('browser_version')} />
          </Field>
        )}
      </div>
      <SelectField
        name="user_agent_mode"
        label="User agent"
        hint="Automatic is derived from the persona and build."
        options={[
          { value: 'automatic', label: 'Automatic' },
          { value: 'custom', label: 'Custom (advanced)' },
        ]}
      />
      {uaMode === 'custom' && (
        <Field label="Custom user agent" error={formState.errors.custom_user_agent?.message}>
          <Textarea rows={2} className="font-mono text-[12px]" {...register('custom_user_agent')} />
        </Field>
      )}
      <p className="text-2xs text-ink-faint">
        Platform is fixed to Windows and the browser to CloakBrowser Chromium. The engine exposes
        one Windows fingerprint platform, not separate Windows 10/11 personas.
      </p>
    </div>
  );
};

// --- Step 4: Window and appearance ------------------------------------------

const WindowStep: FC<{ refs: WizardRefs }> = () => {
  const { register, formState } = useFormContext<ProfileWizardValues>();
  const mode = useWatch<ProfileWizardValues>({ name: 'window_mode' }) as string;
  return (
    <div className="space-y-4">
      <SelectField
        name="window_mode"
        label="Window mode"
        options={[
          { value: 'maximized', label: 'Maximized (recommended)' },
          { value: 'custom', label: 'Custom size' },
        ]}
      />
      {mode === 'custom' && (
        <div className="grid grid-cols-2 gap-4">
          <Field label="Width" error={formState.errors.window_width?.message}>
            <Input {...register('window_width')} placeholder="1920" />
          </Field>
          <Field label="Height" error={formState.errors.window_height?.message}>
            <Input {...register('window_height')} placeholder="1080" />
          </Field>
        </div>
      )}
      <SelectField
        name="color_scheme"
        label="Color scheme"
        options={[
          { value: 'system', label: 'System' },
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' },
        ]}
      />
      <p className="text-2xs text-ink-faint">
        CloakBrowser uses real headed window geometry so screen, outer-window, and inner-window
        dimensions stay coherent. Screen resolution is not spoofed independently.
      </p>
    </div>
  );
};

// --- Step 5: Cookies and storage --------------------------------------------

const CookiesStep: FC<{ refs: WizardRefs }> = ({ refs }) => (
  <div className="space-y-3">
    <p className="text-[13px] text-ink-muted">
      Version 1 supports importing and exporting cookies, not a cell-by-cell editor. Cookies, local
      storage, and login state live inside the profile&apos;s dedicated user-data directory — never
      in the profile database row.
    </p>
    <div className="rounded-md border border-line bg-surface-sunken p-3 text-2xs text-ink-muted">
      {refs.isEdit
        ? 'Use the row action “Import cookies” to load a cookie set into this profile.'
        : 'Save the profile first, then use its row action “Import cookies”. New profiles start with an empty cookie jar.'}
    </div>
  </div>
);

// --- Step 6: Extensions ------------------------------------------------------

const ExtensionsStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const { control } = useFormContext<ProfileWizardValues>();
  return (
    <div className="space-y-3">
      <Controller
        control={control}
        name="extension_ids"
        render={({ field }) => (
          <div className="space-y-2">
            {refs.extensions.length === 0 && (
              <p className="text-2xs text-ink-faint">No local extensions registered.</p>
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
                    <p className="data text-2xs text-ink-faint">{ext.path}</p>
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
      <Warning>
        Identical uncommon extensions across profiles can link their identities. Prefer common,
        widely-used extensions.
      </Warning>
    </div>
  );
};

// --- Step 7: Advanced behavior ----------------------------------------------

const AdvancedStep: FC<{ refs: WizardRefs }> = () => {
  const { register, formState } = useFormContext<ProfileWizardValues>();
  const downloadMode = useWatch<ProfileWizardValues>({ name: 'download_directory_mode' }) as string;
  const hwMode = useWatch<ProfileWizardValues>({ name: 'hardware_concurrency_mode' }) as string;
  const gpuMode = useWatch<ProfileWizardValues>({ name: 'gpu_mode' }) as string;
  const permissions: { name: keyof ProfileWizardValues; label: string }[] = [
    { name: 'permission_geolocation', label: 'Geolocation' },
    { name: 'permission_notifications', label: 'Notifications' },
    { name: 'permission_camera', label: 'Camera' },
    { name: 'permission_microphone', label: 'Microphone' },
    { name: 'permission_clipboard', label: 'Clipboard' },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <ToggleField
          name="humanize_enabled"
          label="Humanize interactions"
          hint="Human-like mouse, typing, scroll."
        />
        <SelectField
          name="humanize_preset"
          label="Humanize preset"
          options={[
            { value: 'default', label: 'Default' },
            { value: 'careful', label: 'Careful' },
          ]}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ToggleField name="clear_cache_before_launch" label="Clear cache before launch" />
        <ToggleField name="restore_previous_tabs" label="Restore previous tabs" />
      </div>
      <SelectField
        name="download_directory_mode"
        label="Downloads"
        options={[
          { value: 'profile', label: 'Profile download directory' },
          { value: 'custom', label: 'Custom directory' },
        ]}
      />
      {downloadMode === 'custom' && (
        <Field
          label="Custom download directory"
          error={formState.errors.custom_download_directory?.message}
        >
          <Input
            mono
            placeholder="C:\\Downloads\\profile"
            {...register('custom_download_directory')}
          />
        </Field>
      )}
      <Field label="Browser permissions">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {permissions.map((permission) => (
            <label key={permission.name} className="flex flex-col gap-1">
              <span className="text-2xs text-ink-muted">{permission.label}</span>
              <Select {...register(permission.name)} options={PERMISSION_OPTIONS} />
            </label>
          ))}
        </div>
      </Field>
      <ToggleField
        name="ignore_https_errors"
        label="Ignore HTTPS errors"
        hint="Off by default. Lowers security — use only when necessary."
      />
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="hardware_concurrency_mode"
          label="Hardware concurrency"
          options={[
            { value: 'automatic', label: 'Automatic' },
            { value: 'custom', label: 'Custom' },
          ]}
        />
        {hwMode === 'custom' && (
          <Field label="Cores (2–64)" error={formState.errors.hardware_concurrency?.message}>
            <Input {...register('hardware_concurrency')} placeholder="12" />
          </Field>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <SelectField
          name="gpu_mode"
          label="GPU"
          options={[
            { value: 'automatic', label: 'Automatic' },
            { value: 'custom_vendor', label: 'Custom vendor' },
          ]}
        />
        {gpuMode === 'custom_vendor' && (
          <Field label="GPU vendor" error={formState.errors.gpu_vendor?.message}>
            <Input {...register('gpu_vendor')} placeholder="Google Inc. (Intel)" />
          </Field>
        )}
      </div>
      <Field
        label="Additional Chromium arguments"
        hint="Space-separated. Manager-owned and unsafe flags are rejected."
        error={formState.errors.additional_args?.message}
      >
        <Input mono placeholder="--disable-features=Foo" {...register('additional_args')} />
      </Field>
      <p className="text-2xs text-ink-faint">Profiles run headed, one instance at a time.</p>
    </div>
  );
};

// --- Step 8: Review ----------------------------------------------------------

const ReviewStep: FC<{ refs: WizardRefs }> = ({ refs }) => {
  const values = useWatch<ProfileWizardValues>() as ProfileWizardValues;
  const proxy = refs.proxies.find((p) => p.id === values.proxy_id);
  const urls = values.startup_urls_text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
  const rows: [string, string][] = [
    ['Name', values.name || '—'],
    ['Fingerprint preset', values.fingerprint_preset],
    ['Fingerprint seed', values.fingerprint_seed],
    [
      'Browser',
      values.browser_version_mode === 'pinned'
        ? `Pinned ${values.browser_version}`
        : `Installed (${refs.browserVersion})`,
    ],
    ['Locale / timezone', `${values.locale || '—'} · ${values.timezone || '—'}`],
    ['Proxy', proxy ? `${proxy.label} (${proxy.masked_endpoint})` : 'Direct connection'],
    [
      'Window',
      values.window_mode === 'custom'
        ? `${values.window_width}×${values.window_height}`
        : 'Maximized',
    ],
    ['Startup URLs', urls.length ? `${urls.length}` : 'None'],
  ];
  const warnings: string[] = [];
  if (values.geo_mode === 'proxy' && !values.proxy_id)
    warnings.push('Geo source is "from proxy" but no proxy is assigned.');
  if (proxy && proxy.reputation === 'malicious')
    warnings.push('The assigned proxy has a malicious reputation.');
  if (proxy && proxy.assigned_profile_count > (refs.isEdit ? 1 : 0))
    warnings.push('The assigned proxy is shared with other profiles.');
  if (values.ignore_https_errors)
    warnings.push('Ignore-HTTPS-errors is enabled; this lowers security.');
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <FingerprintGlyph seed={values.fingerprint_seed || '0'} size={40} />
        <div>
          <p className="font-display text-base font-semibold text-ink">
            {values.name || 'Untitled profile'}
          </p>
          <p className="text-2xs text-ink-faint">Review before saving.</p>
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
  title: string;
  description: string;
  Component: FC<{ refs: WizardRefs }>;
}

export const WIZARD_STEPS: WizardStep[] = [
  {
    id: 'general',
    title: 'General',
    description: 'Name, folder, tags, startup URLs',
    Component: GeneralStep,
  },
  {
    id: 'proxy-location',
    title: 'Proxy & location',
    description: 'Connection, geo, WebRTC',
    Component: ProxyLocationStep,
  },
  {
    id: 'identity',
    title: 'Browser identity',
    description: 'Fingerprint, version, user agent',
    Component: IdentityStep,
  },
  {
    id: 'window',
    title: 'Window & appearance',
    description: 'Window mode, color scheme',
    Component: WindowStep,
  },
  {
    id: 'cookies',
    title: 'Cookies & storage',
    description: 'Import and export',
    Component: CookiesStep,
  },
  {
    id: 'extensions',
    title: 'Extensions',
    description: 'Local unpacked extensions',
    Component: ExtensionsStep,
  },
  {
    id: 'advanced',
    title: 'Advanced behavior',
    description: 'Humanize, downloads, hardware',
    Component: AdvancedStep,
  },
  { id: 'review', title: 'Review', description: 'Confirm and save', Component: ReviewStep },
];
