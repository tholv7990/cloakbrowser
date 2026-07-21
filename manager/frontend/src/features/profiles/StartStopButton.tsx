import { Play, Square } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import type { ProfileView } from '@/types/api';
import { useCapabilities } from '@/hooks/useAppData';
import { useT } from '@/i18n';
import { useStartProfile, useStopProfile } from './api';

/** Runtime control that mirrors the authoritative runtime_state (spec §6). */
export function StartStopButton({ profile }: { profile: ProfileView }) {
  const t = useT();
  const runtimeEnabled = useCapabilities().browser_runtime;
  const start = useStartProfile();
  const stop = useStopProfile();
  const state = profile.runtime_state;

  if (!runtimeEnabled) {
    return (
      <Button
        size="sm"
        variant="subtle"
        disabled
        className="w-[74px]"
        title={t('runtime.unavailable')}
      >
        <Play className="h-3.5 w-3.5" /> {t('runtime.start')}
      </Button>
    );
  }

  if (state === 'starting' || state === 'stopping') {
    return (
      <Button size="sm" variant="subtle" disabled className="w-[74px]">
        <Spinner /> {state === 'starting' ? t('runtime.start') : t('runtime.stop')}
      </Button>
    );
  }
  if (state === 'running') {
    return (
      <Button
        size="sm"
        variant="danger"
        className="w-[74px]"
        onClick={() => stop.mutate(profile.id)}
        loading={stop.isPending}
      >
        {!stop.isPending && <Square className="h-3.5 w-3.5" />} {t('runtime.stop')}
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      variant="primary"
      className="w-[74px]"
      onClick={() => start.mutate(profile.id)}
      loading={start.isPending}
    >
      {!start.isPending && <Play className="h-3.5 w-3.5" />} {t('runtime.start')}
    </Button>
  );
}
