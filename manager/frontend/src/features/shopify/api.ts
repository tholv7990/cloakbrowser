/**
 * Shopify Builder data hooks. Draft-only: staging changes nothing remote;
 * execution is confirmed and then polled (~1s) while the plan runs.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type {
  AiImageSettings,
  ConnectStorePayload,
  CreatePlanPayload,
  StoreProfile,
} from '@/types/api';
import { useToast } from '@/components/ui/Toast';

export function useStores() {
  return useQuery({ queryKey: queryKeys.shopifyStores, queryFn: () => api.listStores() });
}

export function useConnectStore() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: ConnectStorePayload) => api.connectStore(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shopify', 'stores'] });
      toast({ title: 'Store connected', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Could not connect store', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useInspectStore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.inspectStore(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shopify', 'stores'] }),
  });
}

export function useSetNetworkRoute() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; proxyId: string | null }) =>
      api.setStoreNetworkRoute(input.id, input.proxyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shopify', 'stores'] }),
  });
}

export function useDeleteStore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteStore(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shopify', 'stores'] }),
  });
}

export function useStoreProfile(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.shopifyStoreProfile(id) : ['shopify', 'store', 'none', 'profile'],
    queryFn: () => api.getStoreProfile(id as string),
    enabled: Boolean(id),
  });
}

export function useUpdateStoreProfile(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<StoreProfile>) => api.updateStoreProfile(id, patch),
    onSuccess: (profile) => {
      queryClient.setQueryData(queryKeys.shopifyStoreProfile(id), profile);
      queryClient.invalidateQueries({ queryKey: ['shopify', 'stores'] });
    },
  });
}

export function useAiSettings() {
  return useQuery({ queryKey: queryKeys.shopifyAiSettings, queryFn: () => api.getAiSettings() });
}

export function useUpdateAiSettings() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (patch: Partial<AiImageSettings> & { api_key?: string }) =>
      api.updateAiSettings(patch),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.shopifyAiSettings, settings);
      toast({ title: 'AI settings saved', tone: 'success' });
    },
  });
}

export function useThemeLibrary(storeId: string | null) {
  return useQuery({
    queryKey: storeId ? queryKeys.shopifyThemes(storeId) : ['shopify', 'themes', 'none'],
    queryFn: () => api.getThemeLibrary(storeId as string),
    enabled: Boolean(storeId),
  });
}

export function useCatalogs() {
  return useQuery({ queryKey: queryKeys.shopifyCatalogs, queryFn: () => api.listCatalogs() });
}

export function useInspectProductCsv(storeId: string) {
  return useMutation({
    mutationFn: (content: string) => api.inspectProductCsv(storeId, content),
  });
}

export function useCreateBuildPlan(storeId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: CreatePlanPayload) => api.createBuildPlan(storeId, payload),
    onSuccess: (plan) => queryClient.setQueryData(queryKeys.shopifyPlan(plan.id), plan),
    onError: (error) =>
      toast({ title: 'Could not stage plan', description: (error as Error).message, tone: 'danger' }),
  });
}

/** Polls the plan ~1s while it is executing. */
export function useBuildPlan(storeId: string | null, planId: string | null) {
  return useQuery({
    queryKey: planId ? queryKeys.shopifyPlan(planId) : ['shopify', 'plan', 'none'],
    queryFn: () => api.getBuildPlan(storeId as string, planId as string),
    enabled: Boolean(storeId && planId),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 1000 : false),
    refetchIntervalInBackground: false,
  });
}

export function useExecuteBuildPlan(storeId: string) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (planId: string) => api.executeBuildPlan(storeId, planId, true),
    onSuccess: (plan) => queryClient.setQueryData(queryKeys.shopifyPlan(plan.id), plan),
    onError: (error) =>
      toast({ title: 'Could not execute plan', description: (error as Error).message, tone: 'danger' }),
  });
}
