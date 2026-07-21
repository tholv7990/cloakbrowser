import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { ProxyWritePayload } from '@/types/api';
import { useToast } from '@/components/ui/Toast';

export function useProxies() {
  return useQuery({
    queryKey: queryKeys.proxies,
    queryFn: () => api.listProxies(),
    staleTime: 20_000,
  });
}

export function useProxyReports(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.proxyReports(id) : ['proxy', 'reports', 'none'],
    queryFn: () => api.getProxyReports(id!),
    enabled: Boolean(id),
  });
}

function useProxyInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['proxies'] });
    queryClient.invalidateQueries({ queryKey: ['profiles'] });
  };
}

export function useCreateProxy() {
  const invalidate = useProxyInvalidation();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (payload: ProxyWritePayload) => api.createProxy(payload),
    onSuccess: (proxy) => {
      invalidate();
      toast({ title: 'Proxy saved', description: proxy.label, tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not save proxy',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useUpdateProxy() {
  const invalidate = useProxyInvalidation();
  const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ProxyWritePayload }) =>
      api.updateProxy(id, payload),
    onSuccess: (proxy) => {
      invalidate();
      toast({ title: 'Proxy updated', description: proxy.label, tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not update proxy',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useDeleteProxy() {
  const invalidate = useProxyInvalidation();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.deleteProxy(id),
    onSuccess: () => {
      invalidate();
      toast({ title: 'Proxy deleted', tone: 'success' });
    },
    onError: (error) =>
      toast({
        title: 'Could not delete proxy',
        description: (error as Error).message,
        tone: 'danger',
      }),
  });
}

export function useParseProxy() {
  return useMutation({ mutationFn: (raw: string) => api.parseProxy(raw) });
}

export function useQuickTest() {
  const invalidate = useProxyInvalidation();
  return useMutation({
    mutationFn: (id: string) => api.quickTestProxy(id),
    onSuccess: invalidate,
  });
}

export function useQualityTest() {
  const queryClient = useQueryClient();
  const invalidate = useProxyInvalidation();
  return useMutation({
    mutationFn: (id: string) => api.qualityTestProxy(id),
    onSuccess: (report) => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ['proxy', report.proxy_id, 'reports'] });
      queryClient.invalidateQueries({ queryKey: ['diagnostics'] });
    },
  });
}
