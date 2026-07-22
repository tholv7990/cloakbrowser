import { useEffect, useState } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import type { ShopifyStore, StoreCapabilityKey } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { IconButton } from '@/components/ui/IconButton';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Toggle } from '@/components/ui/Toggle';
import { cn } from '@/lib/cn';
import { useT, type TranslationKey } from '@/i18n';
import {
  useAiSettings,
  useCatalogs,
  useCreateBuildPlan,
  useDeleteStore,
  useInspectProductCsv,
  useInspectStore,
  useThemeLibrary,
} from './api';
import { AiSettingsCard } from './AiSettingsCard';

const CAPABILITY_KEYS: StoreCapabilityKey[] = [
  'write_products',
  'write_pages',
  'write_legal_policies',
  'write_navigation',
  'write_themes',
];

type ProductSource = 'catalog' | 'csv';

const SOURCES: { id: ProductSource; key: TranslationKey }[] = [
  { id: 'catalog', key: 'shop.build.productsCatalog' },
  { id: 'csv', key: 'shop.build.productsCsv' },
];

export function StorePanel({
  store,
  onOpenPlan,
}: {
  store: ShopifyStore;
  onOpenPlan: (planId: string) => void;
}) {
  const t = useT();

  const inspectStore = useInspectStore();
  const deleteStore = useDeleteStore();
  const themes = useThemeLibrary(store.id);
  const catalogs = useCatalogs();
  const aiSettings = useAiSettings();
  const inspectCsv = useInspectProductCsv(store.id);
  const createPlan = useCreateBuildPlan(store.id);

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [themeId, setThemeId] = useState('');
  const [preset, setPreset] = useState('');
  const [productSource, setProductSource] = useState<ProductSource>('catalog');
  const [catalogId, setCatalogId] = useState('');
  const [csvText, setCsvText] = useState('');
  const [nicheOverride, setNicheOverride] = useState('');
  const [aiHero, setAiHero] = useState(false);

  const allThemes = [...(themes.data?.integrated ?? []), ...(themes.data?.store ?? [])];
  const selectedTheme = allThemes.find((theme) => theme.id === themeId) ?? null;
  const aiEnabled = aiSettings.data?.enabled ?? false;

  useEffect(() => {
    if (!themes.data) return;
    const flat = [...themes.data.integrated, ...themes.data.store];
    if (flat.length) {
      setThemeId((current) =>
        current && flat.some((theme) => theme.id === current) ? current : flat[0].id,
      );
    }
  }, [themes.data]);

  useEffect(() => {
    if (!selectedTheme) return;
    setPreset((current) =>
      selectedTheme.presets.includes(current) ? current : selectedTheme.presets[0] ?? '',
    );
  }, [selectedTheme]);

  useEffect(() => {
    if (!catalogs.data) return;
    if (catalogs.data.length) {
      setCatalogId((current) =>
        current && catalogs.data.some((catalog) => catalog.id === current)
          ? current
          : catalogs.data[0].id,
      );
    }
  }, [catalogs.data]);

  const themeOptions = allThemes.map((theme) => ({ value: theme.id, label: theme.name }));
  const presetOptions = (selectedTheme?.presets ?? []).map((value) => ({ value, label: value }));
  const catalogOptions = (catalogs.data ?? []).map((catalog) => ({
    value: catalog.id,
    label: `${catalog.name} (${catalog.product_count})`,
  }));

  const stage = () => {
    createPlan.mutate(
      {
        theme_id: themeId,
        preset,
        product_source: productSource,
        catalog_id: productSource === 'catalog' ? catalogId || null : null,
        niche_override: nicheOverride || null,
        ai_hero: aiEnabled && aiHero,
      },
      { onSuccess: (plan) => onOpenPlan(plan.id) },
    );
  };

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-line bg-surface p-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate font-display text-[15px] font-semibold text-ink">{store.label}</p>
            <p className="truncate text-2xs text-ink-faint">{store.shop_domain}</p>
          </div>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => inspectStore.mutate(store.id)}
            loading={inspectStore.isPending}
          >
            <RefreshCw className="h-3.5 w-3.5" /> {t('shop.store.inspect')}
          </Button>
          <IconButton size="sm" label={t('shop.store.delete')} onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-3.5 w-3.5" />
          </IconButton>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-muted">
          <span>
            {t('shop.store.niche')}: {store.niche ?? t('shop.store.notInspected')}
          </span>
          {store.language && (
            <span>
              {t('shop.store.language')}: {store.language}
            </span>
          )}
          <span>{t('shop.store.products', { count: store.product_count ?? 0 })}</span>
          {store.exit_ip && <span>{t('shop.store.exitIp', { ip: store.exit_ip })}</span>}
        </div>

        <div className="mt-3">
          <p className="mb-1.5 text-2xs font-medium text-ink-faint">{t('shop.store.capabilities')}</p>
          <div className="flex flex-wrap gap-1.5">
            {CAPABILITY_KEYS.map((key) => (
              <Badge key={key} tone={store.capabilities[key] ? 'success' : 'neutral'}>
                {t(`shop.cap.${key}` as TranslationKey)}
              </Badge>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-surface p-3">
        <h3 className="mb-3 font-display text-[15px] font-semibold text-ink">
          {t('shop.build.title')}
        </h3>
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('shop.build.theme')}>
              <Select
                value={themeId}
                onChange={(event) => setThemeId(event.target.value)}
                options={themeOptions}
              />
            </Field>
            <Field label={t('shop.build.preset')}>
              <Select
                value={preset}
                onChange={(event) => setPreset(event.target.value)}
                options={presetOptions}
              />
            </Field>
          </div>

          <Field label={t('shop.build.products')}>
            <div className="inline-flex rounded-md border border-line-strong bg-surface-sunken p-0.5">
              {SOURCES.map((source) => (
                <button
                  key={source.id}
                  type="button"
                  onClick={() => setProductSource(source.id)}
                  className={cn(
                    'rounded px-2.5 py-1 text-[13px] font-medium transition-colors',
                    productSource === source.id
                      ? 'bg-surface text-ink'
                      : 'text-ink-muted hover:text-ink',
                  )}
                >
                  {t(source.key)}
                </button>
              ))}
            </div>
          </Field>

          {productSource === 'catalog' ? (
            <Field label={t('shop.build.catalog')}>
              <Select
                value={catalogId}
                onChange={(event) => setCatalogId(event.target.value)}
                options={catalogOptions}
              />
            </Field>
          ) : (
            <Field label={t('shop.build.productsCsv')}>
              <Textarea
                rows={5}
                className="font-mono text-[12px]"
                placeholder={t('shop.build.csvPlaceholder')}
                value={csvText}
                onChange={(event) => setCsvText(event.target.value)}
              />
              <div className="mt-2 flex items-center gap-3">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => inspectCsv.mutate(csvText)}
                  loading={inspectCsv.isPending}
                  disabled={!csvText.trim()}
                >
                  {t('shop.build.csvInspect')}
                </Button>
                {inspectCsv.data && (
                  <span className="text-2xs text-ink-muted">
                    {t('shop.build.csvResult', {
                      total: inspectCsv.data.total,
                      mapped: inspectCsv.data.columns_mapped.length,
                    })}
                  </span>
                )}
              </div>
            </Field>
          )}

          <Field label={t('shop.build.nicheOverride')}>
            <Input value={nicheOverride} onChange={(event) => setNicheOverride(event.target.value)} />
          </Field>

          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[13px] text-ink">{t('shop.build.aiHero')}</p>
              {!aiEnabled && <p className="text-2xs text-ink-faint">{t('shop.build.aiDisabled')}</p>}
            </div>
            <Toggle
              checked={aiEnabled && aiHero}
              onChange={setAiHero}
              disabled={!aiEnabled}
              label={t('shop.build.aiHero')}
            />
          </div>

          <Button
            variant="primary"
            onClick={stage}
            loading={createPlan.isPending}
            disabled={!themeId}
          >
            {t('shop.build.stage')}
          </Button>
        </div>
      </section>

      <AiSettingsCard />

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() =>
          deleteStore.mutate(store.id, { onSuccess: () => setConfirmDelete(false) })
        }
        title={t('shop.store.delete.title')}
        message={t('shop.store.delete.msg')}
        confirmLabel={t('shop.store.delete')}
        tone="danger"
        loading={deleteStore.isPending}
      />
    </div>
  );
}
