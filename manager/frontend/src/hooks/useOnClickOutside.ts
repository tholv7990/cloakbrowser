import { useEffect, type RefObject } from 'react';

/** Fire `handler` on a pointer/focus event outside every provided ref. */
export function useOnClickOutside(
  refs: RefObject<HTMLElement | null> | RefObject<HTMLElement | null>[],
  handler: () => void,
  active = true,
): void {
  useEffect(() => {
    if (!active) return;
    const list = Array.isArray(refs) ? refs : [refs];
    const onEvent = (event: Event) => {
      const target = event.target as Node;
      const inside = list.some((ref) => ref.current?.contains(target));
      if (!inside) handler();
    };
    document.addEventListener('mousedown', onEvent);
    document.addEventListener('touchstart', onEvent);
    return () => {
      document.removeEventListener('mousedown', onEvent);
      document.removeEventListener('touchstart', onEvent);
    };
  }, [refs, handler, active]);
}
