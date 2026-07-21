import type { Config } from 'tailwindcss';

/**
 * Original CloakBrowser visual system. Colors are driven by CSS custom
 * properties (see src/styles/tokens.css) so light/dark/system themes swap
 * variable values rather than utility classes. Channels are stored as
 * space-separated RGB so Tailwind opacity modifiers keep working.
 */
const rgb = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: rgb('--cb-canvas'),
        surface: {
          DEFAULT: rgb('--cb-surface'),
          raised: rgb('--cb-surface-raised'),
          sunken: rgb('--cb-surface-sunken'),
        },
        line: {
          DEFAULT: rgb('--cb-line'),
          strong: rgb('--cb-line-strong'),
        },
        ink: {
          DEFAULT: rgb('--cb-ink'),
          muted: rgb('--cb-ink-muted'),
          faint: rgb('--cb-ink-faint'),
        },
        accent: {
          DEFAULT: rgb('--cb-accent'),
          hover: rgb('--cb-accent-hover'),
          fg: rgb('--cb-accent-fg'),
        },
        success: rgb('--cb-success'),
        warning: rgb('--cb-warning'),
        danger: rgb('--cb-danger'),
        info: rgb('--cb-info'),
        neutral: rgb('--cb-neutral'),
      },
      fontFamily: {
        sans: [
          'Segoe UI',
          'system-ui',
          '-apple-system',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        display: ['Space Grotesk', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '6px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        panel: '0 1px 2px 0 rgb(0 0 0 / 0.10), 0 6px 16px -6px rgb(0 0 0 / 0.20)',
        pop: '0 10px 30px -8px rgb(0 0 0 / 0.30), 0 3px 8px -3px rgb(0 0 0 / 0.18)',
        focus: '0 0 0 3px rgb(var(--cb-accent) / 0.30)',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-in-right': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.97)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        pulse: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.4' } },
      },
      animation: {
        'fade-in': 'fade-in 120ms ease-out',
        'slide-in-right': 'slide-in-right 180ms cubic-bezier(0.22, 1, 0.36, 1)',
        'scale-in': 'scale-in 120ms ease-out',
      },
    },
  },
  plugins: [],
} satisfies Config;
