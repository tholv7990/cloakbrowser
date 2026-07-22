import { useState } from 'react';
import { AlertTriangle, FolderPlus, Puzzle, RefreshCw, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/states';
import { useT } from '@/i18n';
import type { Extension } from '@/types/api';
import {
  useExtensions,
  useRegisterExtension,
  useUnregisterExtension,
  useUpdateExtension,
} from './api';

export function ExtensionsPage() {
  const t = useT();
  const extensions = useExtensions();
  const register = useRegisterExtension();
  const update = useUpdateExtension();
  const unregister = useUnregisterExtension();
  const [registerOpen, setRegisterOpen] = useState(false);
  const [directory, setDirectory] = useState('');
  const [remove, setRemove] = useState<Extension | null>(null);

  const registerDirectory = () => {
    register.mutate(directory, {
      onSuccess: () => {
        setDirectory('');
        setRegisterOpen(false);
      },
    });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 px-5 py-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold text-ink">{t('ext.title')}</h2>
          <p className="text-[13px] text-ink-muted">{t('ext.subtitle')}</p>
        </div>
        <Button variant="primary" onClick={() => setRegisterOpen(true)}>
          <FolderPlus className="h-4 w-4" /> {t('ext.register')}
        </Button>
      </div>

      <p className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-3 text-[13px] text-warning">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {t('ext.correlationWarning')}
      </p>

      {extensions.isLoading ? (
        <LoadingBlock label={t('ext.loading')} />
      ) : extensions.isError ? (
        <ErrorState
          message={(extensions.error as Error).message}
          onRetry={() => extensions.refetch()}
        />
      ) : extensions.data?.length ? (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {extensions.data.map((extension) => (
            <li key={extension.id} className="flex flex-wrap items-center gap-3 p-3">
              <Puzzle className="h-4 w-4 text-accent" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink">{extension.name}</span>
                  <Badge tone={extension.enabled ? 'success' : 'neutral'}>
                    {extension.enabled ? t('ext.enabled') : t('ext.disabled')}
                  </Badge>
                  <Badge tone="neutral">MV{extension.manifest_version}</Badge>
                </div>
                <p className="data truncate text-2xs text-ink-faint">{extension.directory}</p>
                <p className="text-2xs text-ink-muted">
                  {t('ext.version', { version: extension.version })}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  update.mutate({ id: extension.id, patch: { enabled: !extension.enabled } })
                }
              >
                {extension.enabled ? t('ext.disable') : t('ext.enable')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => update.mutate({ id: extension.id, patch: { refresh: true } })}
              >
                <RefreshCw className="h-3.5 w-3.5" /> {t('ext.refresh')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setRemove(extension)}>
                <Trash2 className="h-3.5 w-3.5" /> {t('ext.unregister')}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title={t('ext.empty.title')} description={t('ext.empty.desc')} />
      )}

      <Modal
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        title={t('ext.registerTitle')}
        description={t('ext.registerDesc')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRegisterOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={!directory.trim()}
              loading={register.isPending}
              onClick={registerDirectory}
            >
              {t('ext.registerAction')}
            </Button>
          </>
        }
      >
        <Field label={t('ext.directory')}>
          <Input
            aria-label={t('ext.directory')}
            value={directory}
            onChange={(event) => setDirectory(event.target.value)}
          />
        </Field>
        {register.isError && (
          <p className="mt-2 text-2xs text-danger">{(register.error as Error).message}</p>
        )}
      </Modal>

      <ConfirmDialog
        open={Boolean(remove)}
        onClose={() => setRemove(null)}
        onConfirm={() =>
          remove && unregister.mutate(remove.id, { onSuccess: () => setRemove(null) })
        }
        title={t('ext.unregisterTitle')}
        message={t('ext.unregisterDesc')}
        confirmLabel={t('ext.unregister')}
        tone="danger"
        loading={unregister.isPending}
      />
    </div>
  );
}
