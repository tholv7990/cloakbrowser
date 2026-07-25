/**
 * The admin dashboard is styled by the SAME system as the manager frontend:
 * this config only redirects `content` at the admin page, so every colour,
 * font and shadow comes from manager/frontend/tailwind.config.ts rather than
 * being re-declared (and drifting) here.
 */
import type { Config } from 'tailwindcss';
import base from '../../../../manager/frontend/tailwind.config';

export default {
  ...base,
  content: ['../static/index.html'],
} satisfies Config;
