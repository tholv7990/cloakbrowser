import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type {
  AppCapabilities,
  BrowserInfo,
  Extension,
  Folder,
  Tag,
  WorkflowStatus,
} from '@/types/api';
import { useFolders } from '@/features/folders/api';
import { useTags, useWorkflowStatuses } from './useReferenceData';

/** GET /app/bootstrap — canonical minimal app info + feature flags. */
export function useBootstrap() {
  return useQuery({
    queryKey: queryKeys.bootstrap,
    queryFn: () => api.bootstrap(),
    staleTime: 60_000,
  });
}

/** Fail open: until bootstrap resolves (or if it errors), every feature is
 * treated as available so a transient blip never hides the whole app. Once the
 * backend reports a flag off, the matching nav/route/action degrades. */
const ALL_CAPABILITIES: AppCapabilities = {
  authentication: true,
  profiles: true,
  catalogs: true,
  proxy_management: true,
  browser_runtime: true,
  fingerprint_diagnostics: true,
  settings: true,
};

export function useCapabilities(): AppCapabilities {
  const bootstrap = useBootstrap();
  return bootstrap.data?.capabilities ?? ALL_CAPABILITIES;
}

/** GET /app/version — manager/CloakBrowser/Chromium versions. */
export function useVersion() {
  return useQuery({ queryKey: queryKeys.version, queryFn: () => api.version(), staleTime: 60_000 });
}

export interface AppData {
  folders: Folder[];
  tags: Tag[];
  statuses: WorkflowStatus[];
  extensions: Extension[];
  browser: BrowserInfo;
  browserVersion: string;
  runningCount: number;
  profileRoot: string;
  isLoading: boolean;
  isError: boolean;
}

/**
 * Composed app data sourced from the endpoints that actually exist
 * (folders/tags/workflow-statuses/version). The backend's /app/bootstrap is
 * minimal and does not aggregate the catalog. Fields with no backend endpoint
 * yet (extensions, running count, profile root) default gracefully — see
 * docs/frontend-backend-contract-questions.md.
 */
export function useAppData(): AppData {
  const folders = useFolders();
  const tags = useTags();
  const statuses = useWorkflowStatuses();
  const version = useVersion();

  const cloakVersion = version.data?.cloakbrowser_version ?? '';
  return {
    folders: folders.data ?? [],
    tags: tags.data ?? [],
    statuses: statuses.data ?? [],
    extensions: [],
    browser: {
      name: 'CloakBrowser Chromium',
      version: cloakVersion,
      chromium_version: version.data?.chromium_version ?? '',
      path_present: true,
    },
    browserVersion: cloakVersion,
    runningCount: 0,
    profileRoot: '',
    isLoading: folders.isLoading || tags.isLoading || statuses.isLoading || version.isLoading,
    isError: folders.isError || tags.isError || statuses.isError || version.isError,
  };
}
