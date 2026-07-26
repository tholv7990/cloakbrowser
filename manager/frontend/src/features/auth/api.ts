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
    // onSettled, not onSuccess: signing out must end the local session even when
    // the server call fails. If the session had already expired, logout itself
    // 401s - and clearing only on success left the user on a dead page that
    // looked signed in until the next action reported "please log in".
    onSettled: () => {
      setCsrfToken(null);
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== 'auth',
      });
      void queryClient.resetQueries({
        queryKey: ['auth', 'session'],
        exact: true,
      });
    },
  });
}
