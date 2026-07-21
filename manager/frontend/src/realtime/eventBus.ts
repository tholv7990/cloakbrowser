import type { AppEvent } from '@/types/events';

type Handler = (event: AppEvent) => void;

/** Tiny typed pub/sub. One bus fans WebSocket (or mock) events out to the app. */
export class EventBus {
  private handlers = new Set<Handler>();

  on(handler: Handler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  emit(event: AppEvent): void {
    for (const handler of this.handlers) handler(event);
  }
}
