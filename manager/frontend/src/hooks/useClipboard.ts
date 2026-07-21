import { useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';

/** Copy a safe display value and confirm via toast. Callers pass only non-secret fields. */
export function useClipboard(): (value: string, label: string) => Promise<void> {
  const { toast } = useToast();
  return useCallback(
    async (value: string, label: string) => {
      try {
        await navigator.clipboard.writeText(value);
        toast({ title: `Copied ${label}`, tone: 'success' });
      } catch {
        toast({ title: `Could not copy ${label}`, tone: 'danger' });
      }
    },
    [toast],
  );
}
