import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api';
import type { AccountActivateRequest, EmailPasswordRequest } from '@/types/api';

const LICENSE_KEY = ['license'] as const;
const ACCOUNT_KEY = ['account'] as const;

/** Offline-verified license state; drives the LicenseGate. */
export function useLicense() {
  return useQuery({ queryKey: LICENSE_KEY, queryFn: () => api.licenseStatus(), retry: false });
}

export function useAccount() {
  return useQuery({ queryKey: ACCOUNT_KEY, queryFn: () => api.accountStatus(), retry: false });
}

function useRefreshGate() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: LICENSE_KEY });
    queryClient.invalidateQueries({ queryKey: ACCOUNT_KEY });
  };
}

export function useAccountLogin() {
  const refresh = useRefreshGate();
  return useMutation({
    mutationFn: (payload: EmailPasswordRequest) => api.accountLogin(payload),
    onSuccess: refresh,
  });
}

export function useAccountActivate() {
  const refresh = useRefreshGate();
  return useMutation({
    mutationFn: (payload: AccountActivateRequest) => api.accountActivate(payload),
    onSuccess: refresh,
  });
}

export function useAccountRefresh() {
  const refresh = useRefreshGate();
  return useMutation({ mutationFn: () => api.accountRefresh(), onSuccess: refresh });
}

export function useAccountLogout() {
  const refresh = useRefreshGate();
  return useMutation({ mutationFn: () => api.accountLogout(), onSuccess: refresh });
}
