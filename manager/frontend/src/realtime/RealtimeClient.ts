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
        // Mock-style per-event envelope.
        if (parsed && typeof parsed.event === 'string') {
          this.bus.emit(parsed as AppEvent);
          return;
        }
        // Real backend runtime snapshot: { sequence, type: "runtime.snapshot", runtimes: [...] }.
        if (parsed && parsed.type === 'runtime.snapshot' && Array.isArray(parsed.runtimes)) {
          this.bus.emit({
            event: 'runtime.snapshot',
            sequence: typeof parsed.sequence === 'number' ? parsed.sequence : 0,
            timestamp: new Date().toISOString(),
            data: { runtimes: parsed.runtimes },
          });
        }
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
