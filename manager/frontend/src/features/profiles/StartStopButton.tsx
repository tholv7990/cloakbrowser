import { Play, Square } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import type { ProfileView } from '@/types/api';
import { useStartProfile, useStopProfile } from './api';

/** Runtime control that mirrors the authoritative runtime_state (spec §6). */
export function StartStopButton({ profile }: { profile: ProfileView }) {
  const start = useStartProfile();
  const stop = useStopProfile();
  const state = profile.runtime_state;

  if (state === 'starting' || state === 'stopping') {
    return (
      <Button size="sm" variant="subtle" disabled className="w-[74px]">
        <Spinner /> {state === 'starting' ? 'Start' : 'Stop'}
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
        {!stop.isPending && <Square className="h-3.5 w-3.5" />} Stop
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
      {!start.isPending && <Play className="h-3.5 w-3.5" />} Start
    </Button>
  );
}
