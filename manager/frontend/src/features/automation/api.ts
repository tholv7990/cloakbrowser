/**
 * Automation data hooks. Recordings and runs are polled while live (and paused
 * when the tab is hidden), mirroring the resource monitor's poll-when-watched
 * model rather than pushing over the WebSocket.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type {
  AutomationStep,
  ShopCheckCleanupPayload,
  ShopCheckEmailResult,
  ShopCheckRunCreatePayload,
  StartRunPayload,
} from '@/types/api';
import { useToast } from '@/components/ui/Toast';

export function useTemplates() {
  return useQuery({ queryKey: queryKeys.automationTemplates, queryFn: () => api.listTemplates() });
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.deleteTemplate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation', 'templates'] }),
    onError: (error) =>
      toast({ title: 'Could not delete template', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useSaveTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; name: string; description: string; steps: AutomationStep[] }) =>
      api.saveTemplate(input.id, {
        name: input.name,
        description: input.description,
        steps: input.steps,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation', 'templates'] }),
  });
}

export function useStartRecording() {
  const { toast } = useToast();
  return useMutation({
    mutationFn: (input: { name: string; profile_id: string; description: string }) =>
      api.startRecording(input),
    onError: (error) =>
      toast({ title: 'Could not start recording', description: (error as Error).message, tone: 'danger' }),
  });
}

/** Polls the live recording ~900ms while it is recording. */
export function useRecording(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.automationRecording(id) : ['automation', 'recording', 'none'],
    queryFn: () => api.getRecording(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === 'recording' ? 900 : false),
    refetchIntervalInBackground: false,
  });
}

export function useStopRecording() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.stopRecording(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation', 'templates'] }),
  });
}

export function useCancelRecording() {
  return useMutation({ mutationFn: (id: string) => api.cancelRecording(id) });
}

export function useStartRun() {
  const { toast } = useToast();
  return useMutation({
    mutationFn: (input: { templateId: string; payload: StartRunPayload }) =>
      api.startRun(input.templateId, input.payload),
    onError: (error) =>
      toast({ title: 'Could not start run', description: (error as Error).message, tone: 'danger' }),
  });
}

/** Polls the live run ~1s while it is running. */
export function useRun(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.automationRun(id) : ['automation', 'run', 'none'],
    queryFn: () => api.getRun(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 1000 : false),
    refetchIntervalInBackground: false,
  });
}

/** Optimistically patches the polled run cache with the returned run. */
function useRunAction(action: (runId: string, profileId: string) => Promise<import('@/types/api').AutomationRun>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { runId: string; profileId: string }) => action(input.runId, input.profileId),
    onSuccess: (run) => queryClient.setQueryData(queryKeys.automationRun(run.id), run),
  });
}

export const useContinueRunProfile = () =>
  useRunAction((runId, profileId) => api.continueRunProfile(runId, profileId));
export const useRetryRunProfile = () =>
  useRunAction((runId, profileId) => api.retryRunProfile(runId, profileId));
export const useMarkRunProfileCompleted = () =>
  useRunAction((runId, profileId) => api.markRunProfileCompleted(runId, profileId));

export function useCancelRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelRun(id),
    onSuccess: (run) => queryClient.setQueryData(queryKeys.automationRun(run.id), run),
  });
}

export function useCredentialPool() {
  return useQuery({
    queryKey: queryKeys.automationCredentials,
    queryFn: () => api.getCredentialPool(),
  });
}

export function useImportCredentials() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (text: string) => api.importCredentials(text),
    onSuccess: (pool) => {
      queryClient.setQueryData(queryKeys.automationCredentials, pool);
      toast({ title: 'Credentials imported', tone: 'success' });
    },
    onError: (error) =>
      toast({ title: 'Import failed', description: (error as Error).message, tone: 'danger' }),
  });
}

// --- Shop email phone-OTP check ---------------------------------------------
export function useShopCheckRuns() {
  return useQuery({
    queryKey: queryKeys.shopCheckRuns,
    queryFn: () => api.listShopCheckRuns({ page: 1, page_size: 50 }),
  });
}

export function useCreateShopCheckRun() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: ShopCheckRunCreatePayload) => api.createShopCheckRun(payload),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.shopCheckRuns });
      queryClient.setQueryData(queryKeys.shopCheckRun(result.run.id), result.run);
    },
    onError: (error) =>
      toast({ title: 'Could not start check', description: (error as Error).message, tone: 'danger' }),
  });
}

/** Polls a live run ~1s while it is still preparing/running. */
export function useShopCheckRun(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.shopCheckRun(id) : ['shop-check', 'run', 'none'],
    queryFn: () => api.getShopCheckRun(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data && ['queued', 'preparing', 'running'].includes(query.state.data.status)
        ? 1000
        : false,
    refetchIntervalInBackground: false,
  });
}

export function useShopCheckEmails(
  id: string | null,
  params: { page: number; result: ShopCheckEmailResult | null },
) {
  return useQuery({
    queryKey: id
      ? queryKeys.shopCheckEmails(id, params)
      : ['shop-check', 'run', 'none', 'emails', params],
    queryFn: () =>
      api.listShopCheckEmails(id as string, {
        page: params.page,
        page_size: 50,
        result: params.result,
      }),
    enabled: Boolean(id),
  });
}

export function useCancelShopCheckRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelShopCheckRun(id),
    onSuccess: (run) => queryClient.setQueryData(queryKeys.shopCheckRun(run.id), run),
  });
}

export function useExportShopCheckRun() {
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.exportShopCheckRun(id),
    onSuccess: (result) =>
      toast({
        title: 'Export ready',
        description: `${result.matched_count} matched of ${result.total_rows} — ${result.output_dir}`,
        tone: 'success',
      }),
    onError: (error) =>
      toast({ title: 'Export failed', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useCleanupShopCheckRun() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (input: { id: string; payload: ShopCheckCleanupPayload }) =>
      api.cleanupShopCheckRun(input.id, input.payload),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.shopCheckRun(result.run_id) });
      const failed = result.failed > 0;
      toast({
        title: failed ? 'Cleanup partial' : 'Profiles deleted',
        description: `${result.deleted} deleted${failed ? `, ${result.failed} failed` : ''}.`,
        tone: failed ? 'danger' : 'success',
      });
    },
    onError: (error) =>
      toast({ title: 'Cleanup failed', description: (error as Error).message, tone: 'danger' }),
  });
}
