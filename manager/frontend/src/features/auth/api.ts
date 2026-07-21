import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api';
import { setCsrfToken } from '@/api/config';
import type { EmailPasswordRequest, OwnerSession } from '@/types/api';

export function useAuthStatus() {
  return useQuery({ queryKey: ['auth', 'status'], queryFn: () => api.authStatus(), retry: false });
}

export function useAuthSession(enabled: boolean) {
  return useQuery({
    queryKey: ['auth', 'session'],
    queryFn: async () => {
      const session = await api.authSession();
      setCsrfToken(session.csrf_token);
      return session;
    },
    enabled,
    retry: false,
  });
}

function useSessionMutation(fn: (payload: EmailPasswordRequest) => Promise<OwnerSession>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (session) => {
      setCsrfToken(session.csrf_token);
      queryClient.setQueryData(['auth', 'session'], session);
      queryClient.invalidateQueries({ queryKey: ['auth', 'status'] });
    },
  });
}

export function useLogin() {
  return useSessionMutation((payload) => api.authLogin(payload));
}

export function useSetup() {
  return useSessionMutation((payload) => api.authSetup(payload));
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.authLogout(),
    onSuccess: () => {
      setCsrfToken(null);
      queryClient.clear();
    },
  });
}
