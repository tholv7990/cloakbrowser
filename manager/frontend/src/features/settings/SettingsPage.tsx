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
import { useCheckBrowserUpdate, useSettings, useUpdateSettings } from './api';

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

  if (settings.isLoading || !draft) return <LoadingBlock label="Loading settings…" />;
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
      toast({ title: 'Invalid settings JSON', tone: 'danger' });
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-5 py-6">
      <Section
        title="Storage"
        description="Roots are assigned by the backend; changing them requires a migration."
      >
        <Field label="Profile root">
          <Input readOnly value={draft.profile_root} className="data text-[12px] opacity-80" />
        </Field>
        <Field label="Report root">
          <Input readOnly value={draft.report_root} className="data text-[12px] opacity-80" />
        </Field>
      </Section>

      <Section title="Profile defaults">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Default locale">
            <Input
              value={draft.default_locale}
              onChange={(e) => patch({ default_locale: e.target.value })}
            />
          </Field>
          <Field label="Default timezone">
            <Input
              mono
              value={draft.default_timezone}
              onChange={(e) => patch({ default_timezone: e.target.value })}
            />
          </Field>
          <Field label="Rows per page">
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
          <span className="text-[13px] text-ink">Test proxy before launch by default</span>
          <Toggle
            checked={draft.default_test_before_launch}
            onChange={(value) => patch({ default_test_before_launch: value })}
            label="Test proxy before launch by default"
          />
        </div>
      </Section>

      <Section title="Appearance">
        <Field label="Theme" hint="Also available from the header. Applies immediately.">
          <Select
            value={draft.theme}
            onChange={(e) => {
              const value = e.target.value as ThemePreference;
              patch({ theme: value });
              setTheme(value);
            }}
            options={[
              { value: 'system', label: 'Match system' },
              { value: 'dark', label: 'Dark' },
              { value: 'light', label: 'Light' },
            ]}
          />
        </Field>
      </Section>

      <Section title="Browser binary">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[13px] text-ink">
              {draft.browser.name} {draft.browser.version}
            </p>
            <p className="data text-2xs text-ink-faint">{draft.browser.path}</p>
            <p className="mt-1 text-2xs text-ink-muted">
              {draft.browser.tier === 'pro' ? `Pro · ${draft.license.plan ?? 'licensed'}` : 'Free'}
              {draft.license.session_limit != null &&
                ` · Sessions ${draft.license.active_sessions ?? '—'} / ${draft.license.session_limit}`}
            </p>
          </div>
          {draft.browser.update_available ? (
            <Badge tone="warning">Update available: {draft.browser.latest_version}</Badge>
          ) : (
            <Badge tone="success">Up to date</Badge>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={checkBrowserUpdate.isPending}
          onClick={() => checkBrowserUpdate.mutate()}
        >
          <RefreshCw className="h-3.5 w-3.5" /> Check for updates
        </Button>
      </Section>

      <Section title="Retention">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Log retention (days)">
            <Input
              type="number"
              value={draft.log_retention_days}
              onChange={(e) => patch({ log_retention_days: Number(e.target.value) })}
            />
          </Field>
          <Field label="Trash retention (days)">
            <Input
              type="number"
              value={draft.trash_retention_days}
              onChange={(e) => patch({ trash_retention_days: Number(e.target.value) })}
            />
          </Field>
        </div>
      </Section>

      <Section
        title="Backup"
        description="Manager settings only — never includes proxy passwords or tokens."
      >
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={exportSettings}>
            <Download className="h-3.5 w-3.5" /> Export settings
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="h-3.5 w-3.5" /> Import settings
          </Button>
        </div>
      </Section>

      <div className="sticky bottom-0 flex justify-end gap-2 border-t border-line bg-canvas/80 py-3 backdrop-blur">
        <Button variant="primary" onClick={save} loading={update.isPending}>
          Save settings
        </Button>
      </div>

      <Modal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="Import settings"
        description="Paste an exported settings file. Secrets are never included."
        footer={
          <>
            <Button variant="ghost" onClick={() => setImportOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={importSettings}
              disabled={!importText.trim()}
              loading={update.isPending}
            >
              Import
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
