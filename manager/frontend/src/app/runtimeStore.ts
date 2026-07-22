/**
 * Transient per-profile runtime messages from realtime events. ProfileRead has
 * runtime_state but no message field; the latest human-readable status line
 * lives here (memory only) and is overlaid onto the table view.
 */
import { create } from 'zustand';

interface RuntimeState {
  messages: Record<string, string>;
  runningCount: number | null;
  setMessage: (profileId: string, message: string) => void;
  setRunningCount: (count: number) => void;
}

export const useRuntimeStore = create<RuntimeState>((set) => ({
  messages: {},
  runningCount: null,
  setMessage: (profileId, message) =>
    set((state) => ({ messages: { ...state.messages, [profileId]: message } })),
  setRunningCount: (runningCount) => set({ runningCount }),
}));
