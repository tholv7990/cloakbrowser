import { useState } from 'react';
import { Plus, Store } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { cn } from '@/lib/cn';
import { useT } from '@/i18n';
import { useStores } from './api';
import { ConnectStoreDialog } from './ConnectStoreDialog';
import { StorePanel } from './StorePanel';
import { BuildPlanView } from './BuildPlanView';

export function ShopifyPage() {
  const t = useT();
  const [connectOpen, setConnectOpen] = useState(false);
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);
  const [activePlan, setActivePlan] = useState<{ storeId: string; planId: string } | null>(null);

  const stores = useStores();
  const list = stores.data ?? [];
  const selected = list.find((store) => store.id === selectedStoreId) ?? null;

  return (
    <div className="mx-auto max-w-5xl px-5 py-6">
      {activePlan ? (
        <BuildPlanView
          storeId={activePlan.storeId}
          planId={activePlan.planId}
          onBack={() => setActivePlan(null)}
        />
      ) : (
        <>
          <div className="mb-4 flex items-center justify-between gap-3">
            <p className="text-[13px] text-ink-muted">{t('shop.subtitle')}</p>
            <Button variant="primary" size="sm" onClick={() => setConnectOpen(true)}>
              <Plus className="h-3.5 w-3.5" /> {t('shop.connect')}
            </Button>
          </div>

          {stores.isLoading ? (
            <LoadingBlock label="…" />
          ) : stores.isError ? (
            <ErrorState
              message={(stores.error as Error).message}
              onRetry={() => stores.refetch()}
            />
          ) : list.length === 0 ? (
            <EmptyState
              icon={<Store className="h-5 w-5" />}
              title={t('shop.empty.title')}
              description={t('shop.empty.desc')}
              action={
                <Button variant="primary" size="sm" onClick={() => setConnectOpen(true)}>
                  <Plus className="h-3.5 w-3.5" /> {t('shop.connect')}
                </Button>
              }
            />
          ) : (
            <div className="space-y-4">
              <div>
                <p className="mb-2 font-display text-[15px] font-semibold text-ink">
                  {t('shop.stores')}
                </p>
                <div className="space-y-2">
                  {list.map((store) => (
                    <button
                      key={store.id}
                      type="button"
                      onClick={() => setSelectedStoreId(store.id)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-lg border bg-surface p-3 text-left transition-colors',
                        store.id === selectedStoreId
                          ? 'border-accent'
                          : 'border-line hover:border-line-strong',
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium text-ink">{store.label}</p>
                        <p className="truncate text-2xs text-ink-faint">{store.shop_domain}</p>
                      </div>
                      {store.niche && <Badge tone="neutral">{store.niche}</Badge>}
                      <Badge tone="neutral">
                        {t('shop.store.products', { count: store.product_count ?? 0 })}
                      </Badge>
                    </button>
                  ))}
                </div>
              </div>

              {selected && (
                <StorePanel
                  store={selected}
                  onOpenPlan={(planId) =>
                    setActivePlan({ storeId: selected.id, planId })
                  }
                />
              )}
            </div>
          )}
        </>
      )}

      <ConnectStoreDialog open={connectOpen} onClose={() => setConnectOpen(false)} />
    </div>
  );
}
