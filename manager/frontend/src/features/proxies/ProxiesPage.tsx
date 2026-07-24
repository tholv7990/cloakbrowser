import { useState } from 'react';
import { AlertTriangle, Boxes, Gauge, Globe, Pencil, Plus, Trash2, Zap } from 'lucide-react';
import type { Proxy } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { Badge } from '@/components/ui/Badge';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { ReputationBadge } from '@/components/domain/StatusBadges';
import { formatLatency, formatPercent, relativeTime } from '@/lib/format';
import { CountryFlag } from '@/components/CountryFlag';
import { useT, type TranslationKey } from '@/i18n';
import { useDeleteProxy, useProxies, useQuickTest } from './api';
import { ProvidersDialog } from './ProvidersDialog';
import { ProxyEditorDrawer } from './ProxyEditorDrawer';

export function ProxiesPage() {
  const t = useT();
  const proxies = useProxies();
  const quickTest = useQuickTest();
  const deleteProxy = useDeleteProxy();
  const [editor, setEditor] = useState<{ open: boolean; proxy: Proxy | null }>({
    open: false,
    proxy: null,
  });
  const [toDelete, setToDelete] = useState<Proxy | null>(null);
  const [providersOpen, setProvidersOpen] = useState(false);

  const items = proxies.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <p className="text-[13px] text-ink-muted">{t('proxies.desc')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => setProvidersOpen(true)}>
            <Boxes className="h-3.5 w-3.5" /> {t('prov.button')}
          </Button>
          <Button variant="primary" size="sm" onClick={() => setEditor({ open: true, proxy: null })}>
            <Plus className="h-3.5 w-3.5" /> {t('proxies.add')}
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {proxies.isLoading ? (
          <LoadingBlock label={t('proxies.loading')} />
        ) : proxies.isError ? (
          <ErrorState
            message={(proxies.error as Error).message}
            onRetry={() => proxies.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Globe className="h-5 w-5" />}
            title={t('proxies.empty.title')}
            description={t('proxies.empty.desc')}
            action={
              <Button
                variant="primary"
                size="sm"
                onClick={() => setEditor({ open: true, proxy: null })}
              >
                {t('proxies.add')}
              </Button>
            }
          />
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="border-b border-line text-[11px] uppercase tracking-wide text-ink-faint">
                {[
                  t('proxies.col.label'),
                  t('proxies.col.protocol'),
                  t('proxies.col.endpoint'),
                  t('proxies.col.exitIp'),
                  t('proxies.col.location'),
                  t('proxies.col.type'),
                  t('proxies.col.reputation'),
                  t('proxies.col.latency'),
                  t('proxies.col.assigned'),
                  t('proxies.col.lastChecked'),
                  '',
                ].map((heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="whitespace-nowrap px-3 py-2.5 text-left font-semibold"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((proxy) => (
                <tr key={proxy.id} className="border-b border-line/60 hover:bg-surface-sunken/50">
                  <td className="px-3 py-2 text-[13px] font-medium text-ink">{proxy.label}</td>
                  <td className="px-3 py-2">
                    <Badge tone="neutral">{proxy.scheme.toUpperCase()}</Badge>
                  </td>
                  <td
                    className="data px-3 py-2 text-[11px] text-ink-muted"
                    title={proxy.masked_endpoint}
                  >
                    {proxy.masked_endpoint}
                  </td>
                  <td className="data px-3 py-2 text-[12px] text-ink-muted">
                    {proxy.exit_ip ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-[12px] text-ink-muted">
                    {proxy.country ? (
                      <span className="inline-flex items-center gap-1.5">
                        <CountryFlag code={proxy.country} />
                        {proxy.country}
                        {proxy.city ? ` · ${proxy.city}` : ''}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-2 text-[12px] text-ink-muted">
                    {proxy.proxy_type
                      ? `${t(`enum.proxyType.${proxy.proxy_type}` as TranslationKey)} · ${formatPercent(proxy.type_confidence)}`
                      : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <ReputationBadge reputation={proxy.reputation} />
                  </td>
                  <td className="px-3 py-2 text-[12px] text-ink-muted">
                    {formatLatency(proxy.latency_ms)}
                  </td>
                  <td className="px-3 py-2">
                    {proxy.assigned_profile_count > 1 ? (
                      <span
                        className="inline-flex items-center gap-1 text-2xs text-warning"
                        title={t('proxies.sharedWarn')}
                      >
                        <AlertTriangle className="h-3.5 w-3.5" />
                        {proxy.assigned_profile_count}
                      </span>
                    ) : (
                      <span className="text-[12px] text-ink-muted">
                        {proxy.assigned_profile_count}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-[12px] text-ink-muted">
                    {relativeTime(proxy.last_checked_at)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-0.5">
                      <IconButton
                        size="sm"
                        label={t('proxies.quickTest', { label: proxy.label })}
                        disabled={
                          proxy.scheme === 'direct' ||
                          (quickTest.isPending && quickTest.variables === proxy.id)
                        }
                        onClick={() => quickTest.mutate(proxy.id)}
                      >
                        <Zap className="h-3.5 w-3.5" />
                      </IconButton>
                      <IconButton
                        size="sm"
                        label={t('proxies.fullTest', { label: proxy.label })}
                        disabled={proxy.scheme === 'direct'}
                        onClick={() => setEditor({ open: true, proxy })}
                      >
                        <Gauge className="h-3.5 w-3.5" />
                      </IconButton>
                      <IconButton
                        size="sm"
                        label={t('proxies.editLabel', { label: proxy.label })}
                        onClick={() => setEditor({ open: true, proxy })}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </IconButton>
                      <IconButton
                        size="sm"
                        label={t('proxies.deleteLabel', { label: proxy.label })}
                        onClick={() => setToDelete(proxy)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </IconButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ProxyEditorDrawer
        open={editor.open}
        proxy={editor.proxy}
        onClose={() => setEditor({ open: false, proxy: null })}
      />

      <ConfirmDialog
        open={Boolean(toDelete)}
        onClose={() => setToDelete(null)}
        onConfirm={() => {
          if (toDelete) deleteProxy.mutate(toDelete.id, { onSuccess: () => setToDelete(null) });
        }}
        title={t('proxies.delete.title')}
        message={
          toDelete && toDelete.assigned_profile_count > 0
            ? t('proxies.delete.assigned', {
                label: toDelete.label,
                count: toDelete.assigned_profile_count,
              })
            : t('proxies.delete.confirm', { label: toDelete?.label ?? '' })
        }
        confirmLabel={t('proxies.delete.action')}
        tone="danger"
        loading={deleteProxy.isPending}
      />

      <ProvidersDialog open={providersOpen} onClose={() => setProvidersOpen(false)} />
    </div>
  );
}
