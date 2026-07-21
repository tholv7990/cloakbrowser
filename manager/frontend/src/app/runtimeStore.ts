/**
 * Transient per-profile runtime messages from realtime events. ProfileRead has
 * runtime_state but no message field; the latest human-readable status line
 * lives here (memory only) and is overlaid onto the table view.
 */
import { create } from 'zustand';

interface RuntimeState {
  messages: Record<string, string>;
  setMessage: (profileId: string, message: string) => void;
}

export const useRuntimeStore = create<RuntimeState>((set) => ({
  messages: {},
  setMessage: (profileId, message) =>
    set((state) => ({ messages: { ...state.messages, [profileId]: message } })),
}));
