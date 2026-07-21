import { useState } from 'react';
import { AlertTriangle, Gauge, Globe, Pencil, Plus, Trash2, Zap } from 'lucide-react';
import type { Proxy } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { IconButton } from '@/components/ui/IconButton';
import { Badge } from '@/components/ui/Badge';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { ReputationBadge } from '@/components/domain/StatusBadges';
import { formatLatency, formatPercent, relativeTime } from '@/lib/format';
import { useDeleteProxy, useProxies, useQuickTest } from './api';
import { ProxyEditorDrawer } from './ProxyEditorDrawer';

export function ProxiesPage() {
  const proxies = useProxies();
  const quickTest = useQuickTest();
  const deleteProxy = useDeleteProxy();
  const [editor, setEditor] = useState<{ open: boolean; proxy: Proxy | null }>({
    open: false,
    proxy: null,
  });
  const [toDelete, setToDelete] = useState<Proxy | null>(null);

  const items = proxies.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <p className="text-[13px] text-ink-muted">
            Reusable proxy records. Assign them to profiles; passwords are stored in Windows
            Credential Manager and never returned.
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => setEditor({ open: true, proxy: null })}>
          <Plus className="h-3.5 w-3.5" /> Add proxy
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {proxies.isLoading ? (
          <LoadingBlock label="Loading proxies…" />
        ) : proxies.isError ? (
          <ErrorState
            message={(proxies.error as Error).message}
            onRetry={() => proxies.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Globe className="h-5 w-5" />}
            title="No proxies yet"
            description="Add a reusable proxy to assign it to one or more profiles."
            action={
              <Button
                variant="primary"
                size="sm"
                onClick={() => setEditor({ open: true, proxy: null })}
              >
                Add proxy
              </Button>
            }
          />
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="border-b border-line text-[11px] uppercase tracking-wide text-ink-faint">
                {[
                  'Label',
                  'Protocol',
                  'Endpoint',
                  'Exit IP',
                  'Location',
                  'Type',
                  'Reputation',
                  'Latency',
                  'Assigned',
                  'Last checked',
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
                    {proxy.country
                      ? `${proxy.country}${proxy.city ? ` · ${proxy.city}` : ''}`
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-[12px] text-ink-muted">
                    {proxy.proxy_type
                      ? `${proxy.proxy_type} · ${formatPercent(proxy.type_confidence)}`
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
                        title="Assigned to multiple profiles — a shared exit can link identities"
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
                        label={`Quick-test ${proxy.label}`}
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
                        label={`Full test ${proxy.label}`}
                        disabled={proxy.scheme === 'direct'}
                        onClick={() => setEditor({ open: true, proxy })}
                      >
                        <Gauge className="h-3.5 w-3.5" />
                      </IconButton>
                      <IconButton
                        size="sm"
                        label={`Edit ${proxy.label}`}
                        onClick={() => setEditor({ open: true, proxy })}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </IconButton>
                      <IconButton
                        size="sm"
                        label={`Delete ${proxy.label}`}
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
        title="Delete proxy?"
        message={
          toDelete && toDelete.assigned_profile_count > 0
            ? `"${toDelete.label}" is assigned to ${toDelete.assigned_profile_count} profile(s). Reassign them first.`
            : `Delete "${toDelete?.label}"? This cannot be undone.`
        }
        confirmLabel="Delete proxy"
        tone="danger"
        loading={deleteProxy.isPending}
      />
    </div>
  );
}
