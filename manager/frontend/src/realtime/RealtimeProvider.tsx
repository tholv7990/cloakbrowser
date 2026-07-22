/**
 * Owns the single realtime connection and maps events onto the TanStack Query
 * cache so any screen reading server state updates live. Runtime status is
 * patched in place (fast, no refetch); structural changes invalidate and
 * refetch, keeping the backend authoritative.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import type { AppEvent, ConnectionState } from '@/types/events';
import type { Paginated, ProfileRead, RuntimeState } from '@/types/api';
import { useRuntimeStore } from '@/app/runtimeStore';
import { EventBus } from './eventBus';
import { RealtimeClient } from './RealtimeClient';

/** Map the backend runtime vocabulary onto the frontend RuntimeState enum. */
function mapRuntimeState(state: string): RuntimeState {
  switch (state) {
    case 'queued':
    case 'starting':
      return 'starting';
    case 'running':
      return 'running';
    case 'stopping':
      return 'stopping';
    case 'crashed':
      return 'crashed';
    default:
      return 'stopped';
  }
}

interface RealtimeContextValue {
  connectionState: ConnectionState;
  subscribe: (handler: (event: AppEvent) => void) => () => void;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

function patchProfile(
  queryClient: QueryClient,
  profileId: string,
  updater: (profile: ProfileRead) => ProfileRead,
): void {
  queryClient.setQueriesData<Paginated<ProfileRead>>({ queryKey: ['profiles'] }, (old) => {
    if (!old || !Array.isArray(old.items)) return old;
    return { ...old, items: old.items.map((p) => (p.id === profileId ? updater(p) : p)) };
  });
  queryClient.setQueryData<ProfileRead>(['profile', profileId], (old) =>
    old ? updater(old) : old,
  );
}

function applyEvent(queryClient: QueryClient, event: AppEvent): void {
  switch (event.event) {
    case 'profile.runtime.changed': {
      const { profile_id, runtime_state, message } = event.data;
      patchProfile(queryClient, profile_id, (p) => ({ ...p, runtime_state }));
      if (message) useRuntimeStore.getState().setMessage(profile_id, message);
      queryClient.invalidateQueries({ queryKey: ['bootstrap'] });
      break;
    }
    case 'profile.runtime.message': {
      useRuntimeStore.getState().setMessage(event.data.profile_id, event.data.message);
      break;
    }
    case 'profile.updated': {
      patchProfile(queryClient, event.data.profile.id, () => event.data.profile);
      queryClient.invalidateQueries({ queryKey: ['profile', event.data.profile.id] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      break;
    }
    case 'profile.created':
    case 'profile.deleted': {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['folders'] });
      queryClient.invalidateQueries({ queryKey: ['bootstrap'] });
      break;
    }
    case 'proxy.updated':
    case 'proxy.test.completed': {
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      break;
    }
    case 'diagnostic.completed': {
      queryClient.invalidateQueries({ queryKey: ['diagnostics'] });
      break;
    }
    case 'diagnostic.progress': {
      queryClient.invalidateQueries({ queryKey: ['diagnostics'] });
      break;
    }
    case 'manager.reconciliation.completed': {
      queryClient.invalidateQueries({ queryKey: ['profiles'] });
      queryClient.invalidateQueries({ queryKey: ['bootstrap'] });
      break;
    }
    case 'runtime.snapshot': {
      const store = useRuntimeStore.getState();
      store.setRunningCount(event.data.running_session_count);
      for (const runtime of event.data.runtimes) {
        const state = mapRuntimeState(runtime.state);
        patchProfile(queryClient, runtime.profile_id, (p) => ({ ...p, runtime_state: state }));
        if (runtime.last_message) store.setMessage(runtime.profile_id, runtime.last_message);
      }
      break;
    }
    default:
      break;
  }
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const busRef = useRef<EventBus | null>(null);
  if (!busRef.current) busRef.current = new EventBus();
  const clientRef = useRef<RealtimeClient | null>(null);
  if (!clientRef.current) clientRef.current = new RealtimeClient(busRef.current);

  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');

  useEffect(() => {
    const bus = busRef.current!;
    const client = clientRef.current!;
    client.onReconnect = () => queryClient.invalidateQueries();
    const offBus = bus.on((event) => applyEvent(queryClient, event));
    const offState = client.onState(setConnectionState);
    client.start();
    return () => {
      offBus();
      offState();
      client.stop();
    };
  }, [queryClient]);

  const subscribe = useCallback(
    (handler: (event: AppEvent) => void) => busRef.current!.on(handler),
    [],
  );

  const value = useMemo<RealtimeContextValue>(
    () => ({ connectionState, subscribe }),
    [connectionState, subscribe],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useRealtime(): RealtimeContextValue {
  const context = useContext(RealtimeContext);
  if (!context) throw new Error('useRealtime must be used within RealtimeProvider');
  return context;
}
