import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Download, ExternalLink } from 'lucide-react';
import type { CookieFormat, Folder, ProfileView, Proxy, ProfileWrite } from '@/types/api';
import { api } from '@/api';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Select } from '@/components/ui/Select';
import { Textarea } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { LoadingBlock, EmptyState, ErrorState } from '@/components/ui/states';
import { useToast } from '@/components/ui/Toast';
import { relativeTime } from '@/lib/format';
import { useProxyReports, useQuickTest } from '@/features/proxies/api';
import { ProxyQualityReportView, ProxyQuickResult } from '@/features/proxies/ProxyResultViews';
import type { RowDialog } from './ProfileRowActions';
import { useImportCookies, useMoveToTrash, useProfileLogs, useRegenerateFingerprint } from './api';
import { readToWrite } from './view';

interface DialogState {
  type: RowDialog;
  profile: ProfileView;
}

export function ProfileDialogs({
  dialog,
  onClose,
  folders,
  proxies,
}: {
  dialog: DialogState | null;
  onClose: () => void;
  folders: Folder[];
  proxies: Proxy[];
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const profile = dialog?.profile ?? null;
  const id = profile?.id ?? null;

  const logs = useProfileLogs(dialog?.type === 'logs' ? id : null);
  const reports = useProxyReports(
    dialog?.type === 'proxy-report' ? (profile?.proxy?.id ?? null) : null,
  );
  const exportQuery = useQuery({
    queryKey: ['profile', id, 'export'],
    queryFn: () => api.exportProfile(id!),
    enabled: dialog?.type === 'export' && Boolean(id),
  });
  const importCookies = useImportCookies();
  const regenerate = useRegenerateFingerprint();
  const trash = useMoveToTrash();
  const quickTest = useQuickTest();

  // Move-folder / assign-proxy re-send the whole profile because PATCH replaces it.
  const patchProfile = useMutation({
    mutationFn: (write: ProfileWrite) => api.updateProfile(id!, write),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      onClose();
    },
    onError: (error) =>
      toast({
        title: 'Could not update profile',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });

  const [folderId, setFolderId] = useState('');
  const [proxyId, setProxyId] = useState('');
  const [cookieFormat, setCookieFormat] = useState<CookieFormat>('playwright');
  const [cookieContent, setCookieContent] = useState('');

  useEffect(() => {
    if (!dialog) return;
    setFolderId(dialog.profile.folder_id ?? '');
    setProxyId(dialog.profile.proxy?.id ?? '');
    setCookieFormat('playwright');
    setCookieContent('');
    importCookies.reset();
    quickTest.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialog?.type, dialog?.profile.id]);

  if (!dialog || !profile) return null;
  const type = dialog.type;

  if (type === 'regenerate') {
    return (
      <ConfirmDialog
        open
        onClose={onClose}
        onConfirm={() => regenerate.mutate(profile.id, { onSuccess: onClose })}
        title="Generate a new fingerprint?"
        message="This allocates a new stable seed and configuration hash. Websites that already know this profile may see it as a different device. Cookies and storage are kept."
        confirmLabel="Generate new fingerprint"
        tone="danger"
        loading={regenerate.isPending}
      />
    );
  }

  if (type === 'trash') {
    return (
      <ConfirmDialog
        open
        onClose={onClose}
        onConfirm={() => trash.mutate(profile.id, { onSuccess: onClose })}
        title="Move profile to trash?"
        message={`"${profile.name}" moves to the recoverable trash. Its browser data is kept and can be restored until trash retention expires.`}
        confirmLabel="Move to trash"
        tone="danger"
        loading={trash.isPending}
      />
    );
  }

  if (type === 'move-folder') {
    return (
      <Modal
        open
        onClose={onClose}
        title="Move to folder"
        description={profile.name}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={patchProfile.isPending}
              onClick={() =>
                patchProfile.mutate({ ...readToWrite(profile.read), folder_id: folderId || null })
              }
            >
              Move
            </Button>
          </>
        }
      >
        <Field label="Folder" hint="A profile belongs to one folder in this version.">
          <Select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            options={[
              { value: '', label: 'Unfiled (no folder)' },
              ...folders.map((f) => ({ value: f.id, label: f.name })),
            ]}
          />
        </Field>
      </Modal>
    );
  }

  if (type === 'assign-proxy') {
    const selectedProxy = proxies.find((p) => p.id === proxyId) ?? null;
    const multiAssigned = selectedProxy && selectedProxy.assigned_profile_count > 1;
    return (
      <Modal
        open
        onClose={onClose}
        title="Assign proxy"
        description={profile.name}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={patchProfile.isPending}
              onClick={() =>
                patchProfile.mutate({ ...readToWrite(profile.read), proxy_id: proxyId || null })
              }
            >
              Assign
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Reusable proxy">
            <Select
              value={proxyId}
              onChange={(e) => setProxyId(e.target.value)}
              options={[
                { value: '', label: 'Direct connection (no proxy)' },
                ...proxies.map((p) => ({
                  value: p.id,
                  label: `${p.label} · ${p.masked_endpoint}`,
                })),
              ]}
            />
          </Field>
          {multiAssigned && (
            <p className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-2.5 text-2xs text-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              This proxy is already assigned to {selectedProxy!.assigned_profile_count} profiles.
              Reusing one exit across identities can link them.
            </p>
          )}
          {selectedProxy && selectedProxy.scheme !== 'direct' && (
            <div>
              <Button
                variant="secondary"
                size="sm"
                loading={quickTest.isPending}
                onClick={() => quickTest.mutate(selectedProxy.id)}
              >
                Quick-test this proxy
              </Button>
              {quickTest.data && (
                <div className="mt-3">
                  <ProxyQuickResult result={quickTest.data} />
                </div>
              )}
            </div>
          )}
        </div>
      </Modal>
    );
  }

  if (type === 'import-cookies') {
    return (
      <Modal
        open
        onClose={onClose}
        title="Import cookies"
        description={profile.name}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Close
            </Button>
            <Button
              variant="primary"
              disabled={!cookieContent.trim()}
              loading={importCookies.isPending}
              onClick={() =>
                importCookies.mutate({
                  id: profile.id,
                  format: cookieFormat,
                  content: cookieContent,
                })
              }
            >
              Import
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Format">
            <Select
              value={cookieFormat}
              onChange={(e) => setCookieFormat(e.target.value as CookieFormat)}
              options={[
                { value: 'playwright', label: 'Playwright storage state (JSON)' },
                { value: 'json', label: 'JSON cookie array' },
                { value: 'netscape', label: 'Netscape cookies.txt' },
              ]}
            />
          </Field>
          <Field
            label="Paste cookie data"
            hint="Version 1 supports import/export, not cell-by-cell editing."
          >
            <Textarea
              rows={8}
              value={cookieContent}
              onChange={(e) => setCookieContent(e.target.value)}
              placeholder="Paste the exported cookie file contents…"
              className="font-mono text-[12px]"
            />
          </Field>
          {importCookies.data && (
            <div className="rounded-md border border-success/30 bg-success/10 p-2.5 text-2xs text-success">
              Imported {importCookies.data.imported_count} cookies (
              {importCookies.data.skipped_count} skipped).
              {importCookies.data.warnings.map((w) => (
                <p key={w} className="mt-1 text-warning">
                  {w}
                </p>
              ))}
            </div>
          )}
          {importCookies.isError && (
            <p className="text-2xs text-danger">{(importCookies.error as Error).message}</p>
          )}
        </div>
      </Modal>
    );
  }

  if (type === 'export') {
    const download = () => {
      if (!exportQuery.data) return;
      const blob = new Blob([JSON.stringify(exportQuery.data, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${profile.name}.cloakprofile.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    };
    return (
      <Modal
        open
        onClose={onClose}
        title="Export configuration"
        description={`${profile.name} — secrets are excluded`}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Close
            </Button>
            <Button variant="primary" onClick={download} disabled={!exportQuery.data}>
              <Download className="h-3.5 w-3.5" /> Download JSON
            </Button>
          </>
        }
      >
        {exportQuery.isLoading ? (
          <LoadingBlock label="Preparing export…" />
        ) : exportQuery.isError ? (
          <ErrorState
            message={(exportQuery.error as Error).message}
            onRetry={() => exportQuery.refetch()}
          />
        ) : (
          <pre className="max-h-80 overflow-auto rounded-md border border-line bg-surface-sunken p-3 text-[12px] leading-relaxed data text-ink-muted">
            {JSON.stringify(exportQuery.data, null, 2)}
          </pre>
        )}
      </Modal>
    );
  }

  if (type === 'logs') {
    return (
      <Modal open onClose={onClose} title="Runtime logs" description={profile.name} size="lg">
        {logs.isLoading ? (
          <LoadingBlock label="Loading logs…" />
        ) : logs.isError ? (
          <ErrorState message={(logs.error as Error).message} onRetry={() => logs.refetch()} />
        ) : logs.data && logs.data.entries.length > 0 ? (
          <div className="space-y-1 rounded-md border border-line bg-surface-sunken p-3 font-mono text-[12px]">
            {logs.data.entries.map((entry, index) => (
              <div key={index} className="flex gap-3">
                <span className="shrink-0 text-ink-faint">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
                <Badge
                  tone={
                    entry.level === 'error'
                      ? 'danger'
                      : entry.level === 'warning'
                        ? 'warning'
                        : 'neutral'
                  }
                >
                  {entry.level}
                </Badge>
                <span className="text-ink-muted">{entry.message}</span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No logs yet"
            description="Logs appear once this profile has been launched."
          />
        )}
      </Modal>
    );
  }

  if (type === 'proxy-report') {
    const latest = reports.data?.[0] ?? null;
    return (
      <Modal
        open
        onClose={onClose}
        title="Latest proxy-quality report"
        description={profile.proxy?.label ?? undefined}
        size="lg"
      >
        {!profile.proxy?.id ? (
          <EmptyState
            title="No proxy assigned"
            description="Assign a proxy to run quality tests."
          />
        ) : reports.isLoading ? (
          <LoadingBlock label="Loading report…" />
        ) : reports.isError ? (
          <ErrorState
            message={(reports.error as Error).message}
            onRetry={() => reports.refetch()}
          />
        ) : latest ? (
          <div className="space-y-3">
            <p className="text-2xs text-ink-faint">
              Last checked {relativeTime(latest.checked_at)}
            </p>
            <ProxyQualityReportView report={latest} />
          </div>
        ) : (
          <EmptyState
            title="No reports yet"
            description="Run a full quality test on this proxy from the Proxies screen."
            icon={<ExternalLink className="h-5 w-5" />}
          />
        )}
      </Modal>
    );
  }

  return null;
}
