/**
 * Automation data hooks. Recordings and runs are polled while live (and paused
 * when the tab is hidden), mirroring the resource monitor's poll-when-watched
 * model rather than pushing over the WebSocket.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { AutomationStep, StartFactoryPayload, StartRunPayload } from '@/types/api';
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

export function useFactoryJobs() {
  return useQuery({
    queryKey: queryKeys.automationFactory,
    queryFn: () => api.listFactoryJobs(),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => job.status === 'running') ? 1500 : false,
    refetchIntervalInBackground: false,
  });
}

export function useStartFactoryJob() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: StartFactoryPayload) => api.startFactoryJob(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation', 'factory'] }),
    onError: (error) =>
      toast({ title: 'Could not start factory job', description: (error as Error).message, tone: 'danger' }),
  });
}

export function useCancelFactoryJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelFactoryJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation', 'factory'] }),
  });
}
