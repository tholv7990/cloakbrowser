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
  // NB: resolved relative to Tailwind's CWD (manager/frontend), not this file.
  // Getting this wrong silently purges the whole @layer components block.
  content: ['../../cloud/features/admin/static/index.html'],
} satisfies Config;
