/**
 * Local UI preferences only — theme, sidebar, and per-user table layout. These
 * are genuinely client-owned and persisted to localStorage. Server state lives
 * in TanStack Query and is never duplicated here.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ThemePreference = 'light' | 'dark' | 'system';
export type Language = 'en' | 'vi';

export interface UiState {
  theme: ThemePreference;
  language: Language;
  sidebarCollapsed: boolean;
  rowsPerPage: number;
  columnVisibility: Record<string, boolean>;
  columnOrder: string[];
  setTheme: (theme: ThemePreference) => void;
  setLanguage: (language: Language) => void;
  toggleSidebar: () => void;
  setRowsPerPage: (rows: number) => void;
  setColumnVisible: (columnId: string, visible: boolean) => void;
  setColumnOrder: (order: string[]) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: 'system',
      language: 'en',
      sidebarCollapsed: false,
      rowsPerPage: 25,
      columnVisibility: {},
      columnOrder: [],
      setTheme: (theme) => set({ theme }),
      setLanguage: (language) => set({ language }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setRowsPerPage: (rowsPerPage) => set({ rowsPerPage }),
      setColumnVisible: (columnId, visible) =>
        set((state) => ({
          columnVisibility: { ...state.columnVisibility, [columnId]: visible },
        })),
      setColumnOrder: (columnOrder) => set({ columnOrder }),
    }),
    { name: 'cb-manager-ui' },
  ),
);

/** Resolve the effective theme, following the OS when preference is "system". */
export function resolveTheme(preference: ThemePreference): 'light' | 'dark' {
  if (preference === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return preference;
}
