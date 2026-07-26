import type { Config } from 'tailwindcss';

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
    },
  },
  plugins: [],
} satisfies Config;
