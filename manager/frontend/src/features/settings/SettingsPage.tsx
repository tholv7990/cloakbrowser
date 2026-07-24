import { useEffect, useState } from 'react';
import { Download, RefreshCw, Upload } from 'lucide-react';
import type { Settings } from '@/types/api';
import { useUiStore, type ThemePreference } from '@/app/uiStore';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { Badge } from '@/components/ui/Badge';
import { Modal } from '@/components/ui/Modal';
import { LoadingBlock, ErrorState } from '@/components/ui/states';
import { useToast } from '@/components/ui/Toast';
import { useT } from '@/i18n';
import { useCheckBrowserUpdate, useSettings, useUpdateSettings } from './api';
import { BackupsSection } from './BackupsSection';
import { LicenseSection } from './LicenseSection';

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <h2 className="font-display text-[15px] font-semibold text-ink">{title}</h2>
      {description && <p className="mt-0.5 text-2xs text-ink-faint">{description}</p>}
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

export function SettingsPage() {
  const t = useT();
  const settings = useSettings();
  const update = useUpdateSettings();
  const checkBrowserUpdate = useCheckBrowserUpdate();
  const setTheme = useUiStore((state) => state.setTheme);
  const setRowsPerPage = useUiStore((state) => state.setRowsPerPage);
  const { toast } = useToast();

  const [draft, setDraft] = useState<Settings | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');

  useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);

  if (settings.isLoading || !draft) return <LoadingBlock label={t('settings.loading')} />;
  if (settings.isError)
    return (
      <ErrorState message={(settings.error as Error).message} onRetry={() => settings.refetch()} />
    );

  const patch = (part: Partial<Settings>) =>
    setDraft((current) => (current ? { ...current, ...part } : current));

  const save = () => {
    update.mutate({
      default_locale: draft.default_locale,
      default_timezone: draft.default_timezone,
      default_test_before_launch: draft.default_test_before_launch,
      rows_per_page: draft.rows_per_page,
      theme: draft.theme,
      log_retention_days: draft.log_retention_days,
      trash_retention_days: draft.trash_retention_days,
    });
  };

  const exportSettings = () => {
    const { browser, license, profile_root, report_root, ...safe } = draft;
    void browser;
    void license;
    void profile_root;
    void report_root;
    const blob = new Blob([JSON.stringify(safe, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'cloakbrowser-manager-settings.json';
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const importSettings = () => {
    try {
      const parsed = JSON.parse(importText) as Partial<Settings>;
      update.mutate(parsed, { onSuccess: () => setImportOpen(false) });
    } catch {
      toast({ title: t('settings.import.invalid'), tone: 'danger' });
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-5 py-6">
      <Section title={t('settings.storage')} description={t('settings.storage.desc')}>
        <Field label={t('settings.profileRoot')}>
          <Input readOnly value={draft.profile_root} className="data text-[12px] opacity-80" />
        </Field>
        <Field label={t('settings.reportRoot')}>
          <Input readOnly value={draft.report_root} className="data text-[12px] opacity-80" />
        </Field>
      </Section>

      <Section title={t('settings.profileDefaults')}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('settings.defaultLocale')}>
            <Input
              value={draft.default_locale}
              onChange={(e) => patch({ default_locale: e.target.value })}
            />
          </Field>
          <Field label={t('settings.defaultTimezone')}>
            <Input
              mono
              value={draft.default_timezone}
              onChange={(e) => patch({ default_timezone: e.target.value })}
            />
          </Field>
          <Field label={t('settings.rowsPerPage')}>
            <Select
              value={String(draft.rows_per_page)}
              onChange={(e) => {
                const value = Number(e.target.value);
                patch({ rows_per_page: value });
                setRowsPerPage(value);
              }}
              options={[10, 25, 50, 100].map((n) => ({ value: String(n), label: String(n) }))}
            />
          </Field>
        </div>
        <div className="flex items-center justify-between rounded-md border border-line bg-surface-sunken px-3 py-2.5">
          <span className="text-[13px] text-ink">{t('settings.testBeforeLaunch')}</span>
          <Toggle
            checked={draft.default_test_before_launch}
            onChange={(value) => patch({ default_test_before_launch: value })}
            label={t('settings.testBeforeLaunch')}
          />
        </div>
      </Section>

      <Section title={t('settings.appearance')}>
        <Field label={t('settings.theme')} hint={t('settings.theme.hint')}>
          <Select
            value={draft.theme}
            onChange={(e) => {
              const value = e.target.value as ThemePreference;
              patch({ theme: value });
              setTheme(value);
            }}
            options={[
              { value: 'system', label: t('settings.theme.matchSystem') },
              { value: 'dark', label: t('opt.dark') },
              { value: 'light', label: t('opt.light') },
            ]}
          />
        </Field>
      </Section>

      <Section title={t('settings.browserBinary')}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[13px] text-ink">
              {draft.browser.name} {draft.browser.version}
            </p>
            <p className="data text-2xs text-ink-faint">{draft.browser.path}</p>
            <p className="mt-1 text-2xs text-ink-muted">
              {draft.browser.tier === 'pro'
                ? t('settings.proPlan', { plan: draft.license.plan ?? t('settings.licensed') })
                : t('settings.free')}
              {draft.license.session_limit != null &&
                ` · ${t('settings.sessions', {
                  active: draft.license.active_sessions ?? '—',
                  limit: draft.license.session_limit,
                })}`}
            </p>
          </div>
          {draft.browser.update_available ? (
            <Badge tone="warning">
              {t('settings.updateAvailable', { version: draft.browser.latest_version ?? '' })}
            </Badge>
          ) : (
            <Badge tone="success">{t('settings.upToDate')}</Badge>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={checkBrowserUpdate.isPending}
          onClick={() => checkBrowserUpdate.mutate()}
        >
          <RefreshCw className="h-3.5 w-3.5" /> {t('settings.checkUpdates')}
        </Button>
      </Section>

      <LicenseSection />

      <Section title={t('settings.retention')}>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('settings.logRetention')}>
            <Input
              type="number"
              value={draft.log_retention_days}
              onChange={(e) => patch({ log_retention_days: Number(e.target.value) })}
            />
          </Field>
          <Field label={t('settings.trashRetention')}>
            <Input
              type="number"
              value={draft.trash_retention_days}
              onChange={(e) => patch({ trash_retention_days: Number(e.target.value) })}
            />
          </Field>
        </div>
      </Section>

      <Section title={t('settings.backup')} description={t('settings.backup.desc')}>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={exportSettings}>
            <Download className="h-3.5 w-3.5" /> {t('settings.export')}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="h-3.5 w-3.5" /> {t('settings.import')}
          </Button>
        </div>
      </Section>

      <BackupsSection />

      <div className="sticky bottom-0 flex justify-end gap-2 border-t border-line bg-canvas/80 py-3 backdrop-blur">
        <Button variant="primary" onClick={save} loading={update.isPending}>
          {t('settings.save')}
        </Button>
      </div>

      <Modal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title={t('settings.import.title')}
        description={t('settings.import.desc')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setImportOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              onClick={importSettings}
              disabled={!importText.trim()}
              loading={update.isPending}
            >
              {t('settings.import')}
            </Button>
          </>
        }
      >
        <Textarea
          rows={10}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          className="font-mono text-[12px]"
        />
      </Modal>
    </div>
  );
}
