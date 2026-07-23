import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';
import type { Folder } from '@/types/api';
import { api } from '@/api';
import { useT } from '@/i18n';
import { useToast } from '@/components/ui/Toast';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { defaultWizardValues, wizardValuesToPayload } from '@/schemas/profile';
import { parseProxyText } from '@/schemas/proxy';
import { listTemplates } from '@/features/profile-editor/profileTemplates';

type ProxyMode = 'none' | 'one' | 'list';

/**
 * One create flow that scales from a single profile to a batch (BitBrowser /
 * Hidemium style): Count = 1 makes one; Count > 1 makes N named `<pattern> NN`.
 * A pasted proxy list is assigned one-per-profile. Everything else uses the
 * no-leak defaults (or the chosen template); the full wizard is one click away.
 */
export function NewProfileModal({
  open,
  onClose,
  folders,
}: {
  open: boolean;
  onClose: () => void;
  folders: Folder[];
}) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const templates = useMemo(() => (open ? listTemplates() : []), [open]);

  const [name, setName] = useState('');
  const [count, setCount] = useState(1);
  const [folderId, setFolderId] = useState('');
  const [proxyMode, setProxyMode] = useState<ProxyMode>('none');
  const [proxyText, setProxyText] = useState('');
  const [templateId, setTemplateId] = useState('builtin:no-leak');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  useEffect(() => {
    if (!open) return;
    setName('');
    setCount(1);
    setFolderId('');
    setProxyMode('none');
    setProxyText('');
    setTemplateId('builtin:no-leak');
    setBusy(false);
    setDone(0);
  }, [open]);

  const proxyLines = proxyText
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const templateConfig = templates.find((tpl) => tpl.id === templateId)?.config ?? {};

  const proxyForIndex = (i: number): string | null => {
    if (proxyMode === 'none') return null;
    if (proxyMode === 'one') return proxyLines[0] ?? null;
    return proxyLines[i] ?? null; // list: one line per profile
  };

  const shortfall = proxyMode === 'list' && proxyLines.length > 0 && proxyLines.length < count;

  const nameFor = (i: number): string => {
    const base = name.trim();
    if (count === 1) return base || `profile-${Math.floor(Math.random() * 9000) + 1000}`;
    return `${base || 'Profile'} ${String(i + 1).padStart(2, '0')}`;
  };

  const create = async () => {
    setBusy(true);
    setDone(0);
    let ok = 0;
    try {
      for (let i = 0; i < count; i++) {
        const profileName = nameFor(i);
        let proxyId = '';
        const line = proxyForIndex(i);
        if (line) {
          const parsed = parseProxyText(line);
          if (parsed?.host && parsed.port) {
            try {
              const proxy = await api.createProxy({
                label: profileName,
                scheme: parsed.scheme ?? 'http',
                host: parsed.host,
                port: Number(parsed.port),
                username: parsed.username || null,
                password: parsed.password || undefined,
                test_before_launch: true,
              });
              proxyId = proxy.id;
            } catch {
              // Proxy creation failed — still create the profile, just direct.
            }
          }
        }
        const values = defaultWizardValues({
          ...templateConfig,
          name: profileName,
          folder_id: folderId,
          proxy_id: proxyId,
        });
        try {
          await api.createProfile(wizardValuesToPayload(values));
          ok += 1;
        } catch {
          // Skip a single failure; report the shortfall at the end.
        }
        setDone(i + 1);
      }
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      toast({
        title:
          ok === count
            ? t('new.created', { count: ok })
            : t('new.createdPartial', { ok, total: count }),
        tone: ok === count ? 'success' : 'warning',
      });
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const openAdvanced = () => {
    onClose();
    navigate('/profiles/new');
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('new.title')}
      description={t('new.desc')}
      footer={
        <>
          <Button variant="ghost" onClick={openAdvanced} disabled={busy}>
            {t('new.advanced')}
          </Button>
          <Button variant="primary" onClick={create} loading={busy}>
            {busy && count > 1 ? `${done}/${count}` : t(count > 1 ? 'new.createN' : 'new.createOne')}
          </Button>
        </>
      }
    >
      <div className="space-y-3.5">
        <div className="grid grid-cols-[1fr_100px] gap-3">
          <Field label={t('new.namePattern')} hint={t('new.namePatternHint')}>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={count > 1 ? 'Marketplace' : 'e.g. Marketplace US'}
              autoFocus
            />
          </Field>
          <Field label={t('new.count')}>
            <Input
              type="number"
              min={1}
              max={100}
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
              mono
            />
          </Field>
        </div>

        <Field label={t('editor.folder')}>
          <Select
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
            options={[
              { value: '', label: t('dlg.moveFolder.unfiled') },
              ...folders.map((f) => ({ value: f.id, label: f.name })),
            ]}
          />
        </Field>

        <Field label={t('new.proxy')} hint={proxyMode === 'list' ? t('new.proxyListHint') : undefined}>
          <Select
            value={proxyMode}
            onChange={(e) => setProxyMode(e.target.value as ProxyMode)}
            options={[
              { value: 'none', label: t('new.proxyNone') },
              { value: 'one', label: t('new.proxyOne') },
              { value: 'list', label: t('new.proxyList') },
            ]}
          />
        </Field>
        {proxyMode === 'one' && (
          <Input
            value={proxyText}
            onChange={(e) => setProxyText(e.target.value)}
            placeholder="host:port:user:pass"
            className="font-mono text-[12px]"
          />
        )}
        {proxyMode === 'list' && (
          <>
            <Textarea
              rows={Math.min(6, Math.max(3, count))}
              value={proxyText}
              onChange={(e) => setProxyText(e.target.value)}
              placeholder={'host:port:user:pass\nhost:port:user:pass'}
              className="font-mono text-[12px]"
            />
            <p className="text-2xs text-ink-faint">
              {t('new.proxyCount', { have: proxyLines.length, want: count })}
              {shortfall && ` · ${t('new.proxyShortfall')}`}
            </p>
          </>
        )}

        {templates.length > 0 && (
          <Field label={t('editor.tpl.choose')}>
            <Select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              options={templates.map((tpl) => ({ value: tpl.id, label: tpl.name }))}
            />
          </Field>
        )}

        <p className="flex items-center gap-1.5 text-2xs text-ink-faint">
          <Sparkles className="h-3.5 w-3.5 text-accent" /> {t('new.defaultsNote')}
        </p>
      </div>
    </Modal>
  );
}
