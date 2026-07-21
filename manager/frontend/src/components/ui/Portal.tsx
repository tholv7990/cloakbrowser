import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

/** Renders children into document.body so overlays escape table/overflow clips. */
export function Portal({ children }: { children: ReactNode }) {
  const [container] = useState(() => document.createElement('div'));
  useEffect(() => {
    container.setAttribute('data-cb-portal', '');
    document.body.appendChild(container);
    return () => {
      document.body.removeChild(container);
    };
  }, [container]);
  return createPortal(children, container);
}
