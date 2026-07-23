import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, ExternalLink } from 'lucide-react';
import type { CookieFormat, Folder, ProfileView, Proxy, ProfileUpdatePayload } from '@/types/api';
import { api } from '@/api';
import { useT } from '@/i18n';
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
import { useProxyReports } from '@/features/proxies/api';
import { ProxyQualityReportView } from '@/features/proxies/ProxyResultViews';
import { ProxyEditorDrawer } from '@/features/proxies/ProxyEditorDrawer';
import type { RowDialog } from './ProfileRowActions';
import {
  useImportCookies,
  useMoveToTrash,
  useProfileLogs,
  useProfileLogTail,
  useRegenerateFingerprint,
} from './api';
import { handleProfileConflict, PROFILE_CONFLICT_REVIEW_MESSAGE } from './conflicts';

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
  const t = useT();
  const profile = dialog?.profile ?? null;
  const id = profile?.id ?? null;
  const [logsPage, setLogsPage] = useState(1);
  const [logsPageSize, setLogsPageSize] = useState(20);

  const logs = useProfileLogs(dialog?.type === 'logs' ? id : null, logsPage, logsPageSize);
  const logTail = useProfileLogTail(
    dialog?.type === 'logs' ? id : null,
    logsPageSize,
    logsPage === 1,
  );
  const reports = useProxyReports(
    dialog?.type === 'proxy-report' ? (profile?.proxy?.id ?? null) : null,
  );
  const exportQuery = useQuery({
    queryKey: ['profile', id, 'export'],
    queryFn: () => api.exportProfile(id!),
    enabled: dialog?.type === 'export' && Boolean(id),
  });
  const importCookies = useImportCookies();
  const exportCookies = useMutation({
    mutationFn: (format: 'playwright' | 'netscape') => api.exportCookies(id!, format),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const regenerate = useRegenerateFingerprint();
  const trash = useMoveToTrash();

  const patchProfile = useMutation({
    mutationFn: (patch: ProfileUpdatePayload) => api.updateProfile(id!, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      onClose();
    },
    onError: (error) => {
      const conflict = handleProfileConflict(queryClient, error, id!);
      toast({
        title: t('dlg.updateFailed'),
        description: conflict ? PROFILE_CONFLICT_REVIEW_MESSAGE : (error as Error).message,
        tone: 'danger',
      });
    },
  });

  const [folderId, setFolderId] = useState('');
  const [cookieFormat, setCookieFormat] = useState<CookieFormat>('playwright');
  const [cookieContent, setCookieContent] = useState('');

  useEffect(() => {
    if (!dialog) return;
    setFolderId(dialog.profile.folder_id ?? '');
    setCookieFormat('playwright');
    setCookieContent('');
    setLogsPage(1);
    setLogsPageSize(20);
    importCookies.reset();
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
        title={t('dlg.regen.title')}
        message={t('dlg.regen.message')}
        confirmLabel={t('dlg.regen.action')}
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
        title={t('dlg.trash.title')}
        message={t('dlg.trash.message', { name: profile.name })}
        confirmLabel={t('bulk.trash')}
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
        title={t('bulk.moveFolder')}
        description={profile.name}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              loading={patchProfile.isPending}
              onClick={() =>
                patchProfile.mutate({
                  expected_updated_at: profile.read.updated_at,
                  folder_id: folderId || null,
                })
              }
            >
              {t('common.move')}
            </Button>
          </>
        }
      >
        <Field label={t('editor.folder')} hint={t('dlg.moveFolder.hint')}>
          <Select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            options={[
              { value: '', label: t('dlg.moveFolder.unfiled') },
              ...folders.map((f) => ({ value: f.id, label: f.name })),
            ]}
          />
        </Field>
      </Modal>
    );
  }

  if (type === 'assign-proxy') {
    // Click the proxy → open the proxy form directly (BitBrowser-style): edit the
    // profile's current proxy, or fill a fresh one that is assigned on save.
    const assigned = proxies.find((p) => p.id === profile.proxy?.id) ?? null;
    return (
      <ProxyEditorDrawer
        open
        proxy={assigned}
        defaultLabel={profile.name}
        submitLabel={assigned ? undefined : t('pxd.addToProfile')}
        onClose={onClose}
        onSaved={(saved) =>
          patchProfile.mutate({
            expected_updated_at: profile.read.updated_at,
            proxy_id: saved.id,
          })
        }
        onRemove={
          profile.proxy?.id
            ? () =>
                patchProfile.mutate({
                  expected_updated_at: profile.read.updated_at,
                  proxy_id: null,
                })
            : undefined
        }
      />
    );
  }

  if (type === 'import-cookies') {
    return (
      <Modal
        open
        onClose={onClose}
        title={t('row.importCookies')}
        description={profile.name}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.close')}
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
              {t('common.import')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t('dlg.cookies.format')}>
            <Select
              value={cookieFormat}
              onChange={(e) => setCookieFormat(e.target.value as CookieFormat)}
              options={[
                { value: 'playwright', label: t('dlg.cookies.playwright') },
                { value: 'json', label: t('dlg.cookies.json') },
                { value: 'netscape', label: t('dlg.cookies.netscape') },
              ]}
            />
          </Field>
          <Field label={t('dlg.cookies.paste')} hint={t('dlg.cookies.pasteHint')}>
            <Textarea
              rows={8}
              value={cookieContent}
              onChange={(e) => setCookieContent(e.target.value)}
              placeholder={t('dlg.cookies.placeholder')}
              className="font-mono text-[12px]"
            />
          </Field>
          {importCookies.data && (
            <div className="rounded-md border border-success/30 bg-success/10 p-2.5 text-2xs text-success">
              {t('dlg.cookies.imported', {
                imported: importCookies.data.imported_count,
                skipped: importCookies.data.skipped_count,
                rejected: importCookies.data.rejected_count,
              })}
              {importCookies.data.warnings.map((w) => (
                <p key={`${w.index}-${w.code}`} className="mt-1 text-warning">
                  {w.code} ({w.index})
                </p>
              ))}
            </div>
          )}
          {importCookies.isError && (
            <p className="text-2xs text-danger">{(importCookies.error as Error).message}</p>
          )}
          <div className="flex gap-2 border-t border-line pt-3">
            <Button
              variant="secondary"
              size="sm"
              loading={exportCookies.isPending}
              onClick={() => exportCookies.mutate('playwright')}
            >
              {t('dlg.cookies.exportPlaywright')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              loading={exportCookies.isPending}
              onClick={() => exportCookies.mutate('netscape')}
            >
              {t('dlg.cookies.exportNetscape')}
            </Button>
          </div>
          {exportCookies.isError && (
            <p className="text-2xs text-danger">{(exportCookies.error as Error).message}</p>
          )}
        </div>
      </Modal>
    );
  }

  if (type === 'export') {
    const download = () => {
      if (!exportQuery.data) return;
      const url = URL.createObjectURL(exportQuery.data.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = exportQuery.data.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    };
    return (
      <Modal
        open
        onClose={onClose}
        title={t('row.exportConfig')}
        description={t('dlg.export.desc', { name: profile.name })}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.close')}
            </Button>
            <Button variant="primary" onClick={download} disabled={!exportQuery.data}>
              <Download className="h-3.5 w-3.5" /> {t('dlg.export.download')}
            </Button>
          </>
        }
      >
        {exportQuery.isLoading ? (
          <LoadingBlock label={t('dlg.export.preparing')} />
        ) : exportQuery.isError ? (
          <ErrorState
            message={(exportQuery.error as Error).message}
            onRetry={() => exportQuery.refetch()}
          />
        ) : (
          <p className="text-[13px] text-ink-muted">{t('dlg.export.ready')}</p>
        )}
      </Modal>
    );
  }

  if (type === 'logs') {
    const visibleLogs = logsPage === 1 ? logTail.items : (logs.data?.items ?? []);
    return (
      <Modal
        open
        onClose={onClose}
        title={t('dlg.logs.title')}
        description={profile.name}
        size="lg"
      >
        {logs.isLoading || (logsPage === 1 && logTail.isLoading) ? (
          <LoadingBlock label={t('dlg.logs.loading')} />
        ) : logs.isError || (logsPage === 1 && logTail.isError) ? (
          <ErrorState
            message={((logs.error ?? logTail.error) as Error).message}
            onRetry={() => {
              logs.refetch();
              logTail.refetch();
            }}
          />
        ) : logs.data && visibleLogs.length > 0 ? (
          <div className="space-y-3">
            <div className="space-y-1 rounded-md border border-line bg-surface-sunken p-3 font-mono text-[12px]">
              {visibleLogs.map((entry) => (
                <div key={entry.id} className="flex gap-3">
                  <span className="shrink-0 text-ink-faint">
                    {new Date(entry.created_at).toLocaleTimeString()}
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
                  <span className="text-ink-faint">{entry.event}</span>
                  <span className="text-ink-muted">{entry.message}</span>
                </div>
              ))}
              {logsPage === 1 && (
                <p className="pt-2 text-2xs text-ink-faint">{t('dlg.logs.polling')}</p>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 text-2xs text-ink-muted">
              <Select
                aria-label={t('dlg.logs.pageSize')}
                value={String(logsPageSize)}
                onChange={(event) => {
                  setLogsPageSize(Number(event.target.value));
                  setLogsPage(1);
                }}
                options={[20, 50, 100].map((size) => ({
                  value: String(size),
                  label: String(size),
                }))}
              />
              <span>{t('dlg.logs.page', { page: logs.data.page, pages: logs.data.pages })}</span>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('dlg.logs.previousPage')}
                disabled={logsPage <= 1}
                onClick={() => setLogsPage((current) => Math.max(1, current - 1))}
              >
                {t('common.previous')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t('dlg.logs.nextPage')}
                disabled={logsPage >= logs.data.pages}
                onClick={() => setLogsPage((current) => current + 1)}
              >
                {t('common.next')}
              </Button>
            </div>
          </div>
        ) : (
          <EmptyState title={t('dlg.logs.empty.title')} description={t('dlg.logs.empty.desc')} />
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
        title={t('dlg.report.title')}
        description={profile.proxy?.label ?? undefined}
        size="lg"
      >
        {!profile.proxy?.id ? (
          <EmptyState
            title={t('dlg.report.noProxy.title')}
            description={t('dlg.report.noProxy.desc')}
          />
        ) : reports.isLoading ? (
          <LoadingBlock label={t('dlg.report.loading')} />
        ) : reports.isError ? (
          <ErrorState
            message={(reports.error as Error).message}
            onRetry={() => reports.refetch()}
          />
        ) : latest ? (
          <div className="space-y-3">
            <p className="text-2xs text-ink-faint">
              {t('dlg.report.lastChecked', { time: relativeTime(latest.checked_at) })}
            </p>
            <ProxyQualityReportView report={latest} />
          </div>
        ) : (
          <EmptyState
            title={t('dlg.report.empty.title')}
            description={t('dlg.report.empty.desc')}
            icon={<ExternalLink className="h-5 w-5" />}
          />
        )}
      </Modal>
    );
  }

  return null;
}
