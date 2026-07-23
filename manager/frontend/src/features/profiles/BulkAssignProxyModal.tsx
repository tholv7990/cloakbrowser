import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ProfileView } from '@/types/api';
import { api } from '@/api';
import { useT } from '@/i18n';
import { useToast } from '@/components/ui/Toast';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Input';
import { parseProxyText } from '@/schemas/proxy';

/**
 * Bulk-assign proxies to the selected profiles: paste one proxy per line, and
 * profile #1 gets line #1, #2 gets #2, etc. Each proxy is created per-profile
 * (matching the per-profile model) and assigned. Blank/unparseable lines are
 * skipped, leaving that profile's proxy unchanged.
 */
export function BulkAssignProxyModal({
  open,
  onClose,
  profiles,
}: {
  open: boolean;
  onClose: () => void;
  profiles: ProfileView[];
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  useEffect(() => {
    if (open) {
      setText('');
      setBusy(false);
      setDone(0);
    }
  }, [open]);

  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

  const assign = async () => {
    setBusy(true);
    setDone(0);
    let ok = 0;
    try {
      for (let i = 0; i < profiles.length; i++) {
        const line = lines[i];
        const parsed = line ? parseProxyText(line) : null;
        if (parsed?.host && parsed.port) {
          try {
            const proxy = await api.createProxy({
              label: profiles[i].name,
              scheme: parsed.scheme ?? 'http',
              host: parsed.host,
              port: Number(parsed.port),
              username: parsed.username || null,
              password: parsed.password || undefined,
              test_before_launch: true,
            });
            await api.updateProfile(profiles[i].id, {
              expected_updated_at: profiles[i].read.updated_at,
              proxy_id: proxy.id,
            });
            ok += 1;
          } catch {
            // Skip a single failure; the rest still get assigned.
          }
        }
        setDone(i + 1);
      }
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      toast({ title: t('bulk.proxyAssigned', { count: ok }), tone: ok ? 'success' : 'warning' });
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('bulk.proxyTitle')}
      description={t('bulk.proxyDesc', { count: profiles.length })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" onClick={assign} loading={busy} disabled={lines.length === 0}>
            {busy ? `${done}/${profiles.length}` : t('bulk.proxyAssign')}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <Textarea
          rows={Math.min(10, Math.max(4, profiles.length))}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'host:port:user:pass\nhost:port:user:pass'}
          className="font-mono text-[12px]"
          autoFocus
        />
        <p className="text-2xs text-ink-faint">
          {t('new.proxyCount', { have: lines.length, want: profiles.length })}
          {lines.length > 0 && lines.length < profiles.length && ` · ${t('new.proxyShortfall')}`}
        </p>
      </div>
    </Modal>
  );
}
