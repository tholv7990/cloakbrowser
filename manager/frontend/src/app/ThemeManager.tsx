import { useEffect } from 'react';
import { resolveTheme, useUiStore } from './uiStore';

/** Applies the theme preference to <html data-theme> and tracks OS changes. */
export function ThemeManager() {
  const theme = useUiStore((state) => state.theme);

  useEffect(() => {
    const apply = () => {
      document.documentElement.dataset.theme = resolveTheme(theme);
    };
    apply();

    if (theme !== 'system') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [theme]);

  return null;
}
