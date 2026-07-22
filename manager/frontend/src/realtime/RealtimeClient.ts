/**
 * Centralized runtime-event connection (spec §14).
 *
 * - real mode: opens a WebSocket to the token-authenticated /events endpoint,
 *   parses envelopes onto the EventBus, and reconnects with capped backoff. On a
 *   successful *re*connect it fires onReconnect so the app refetches server state
 *   (events are invalidation signals, not the source of truth).
 * - mock mode: subscribes to the in-memory mock emitter and reports connected.
 */
import { API_MODE, WS_URL } from '@/api/config';
import type { AppEvent, ConnectionState } from '@/types/events';
import { mockStore } from '@/mocks/store';
import type { EventBus } from './eventBus';

type StateListener = (state: ConnectionState) => void;

const MAX_BACKOFF_MS = 15_000;

export function normalizeRealtimeFrame(parsed: unknown): AppEvent | null {
  if (!parsed || typeof parsed !== 'object') return null;
  const frame = parsed as Record<string, unknown>;
  if (typeof frame.event === 'string') return frame as unknown as AppEvent;
  const sequence = typeof frame.sequence === 'number' ? frame.sequence : 0;
  if (frame.type === 'runtime.snapshot' && Array.isArray(frame.runtimes)) {
    return {
      event: 'runtime.snapshot',
      sequence,
      timestamp: new Date().toISOString(),
      data: {
        runtimes: frame.runtimes as {
          profile_id: string;
          state: string;
          last_message: string | null;
        }[],
        running_session_count:
          typeof frame.running_session_count === 'number' ? frame.running_session_count : 0,
      },
    };
  }
  if (
    (frame.type === 'diagnostic.progress' || frame.type === 'diagnostic.completed') &&
    frame.diagnostic &&
    typeof frame.diagnostic === 'object'
  ) {
    const diagnostic = frame.diagnostic as Record<string, unknown>;
    return {
      event: frame.type,
      sequence,
      timestamp: new Date().toISOString(),
      data: {
        diagnostic_id: String(diagnostic.id ?? ''),
        profile_id: typeof diagnostic.profile_id === 'string' ? diagnostic.profile_id : null,
        kind: diagnostic.kind,
        status: diagnostic.status,
        progress: typeof diagnostic.progress === 'number' ? diagnostic.progress : 0,
        error_code: typeof diagnostic.error_code === 'string' ? diagnostic.error_code : null,
      },
    } as AppEvent;
  }
  return null;
}

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private mockUnsub: (() => void) | null = null;
  private stateListeners = new Set<StateListener>();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  state: ConnectionState = 'connecting';
  onReconnect: (() => void) | null = null;

  constructor(private bus: EventBus) {}

  start(): void {
    this.stopped = false;
    if (API_MODE === 'mock') {
      this.mockUnsub = mockStore.subscribe((event) => this.bus.emit(event));
      this.setState('connected');
      return;
    }
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.mockUnsub?.();
    this.mockUnsub = null;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
  }

  onState(listener: StateListener): () => void {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => this.stateListeners.delete(listener);
  }

  private setState(state: ConnectionState): void {
    this.state = state;
    for (const listener of this.stateListeners) listener(state);
  }

  private connect(): void {
    this.setState(this.reconnectAttempts === 0 ? 'connecting' : 'reconnecting');
    let socket: WebSocket;
    try {
      // The WS handshake reuses the session cookie + Origin check (spec §3/§14);
      // no token in the URL.
      socket = new WebSocket(WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      const wasReconnect = this.reconnectAttempts > 0;
      this.reconnectAttempts = 0;
      this.setState('connected');
      if (wasReconnect) this.onReconnect?.();
    };

    socket.onmessage = (message) => {
      try {
        const parsed = JSON.parse(message.data);
        const event = normalizeRealtimeFrame(parsed);
        if (event) this.bus.emit(event);
      } catch {
        // Ignore malformed frames; the backend is authoritative on refetch.
      }
    };

    socket.onerror = () => socket.close();

    socket.onclose = () => {
      this.ws = null;
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    this.setState('reconnecting');
    this.reconnectAttempts += 1;
    const backoff = Math.min(MAX_BACKOFF_MS, 500 * 2 ** (this.reconnectAttempts - 1));
    this.reconnectTimer = setTimeout(() => this.connect(), backoff);
  }
}
