import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  base: '/admin/dist/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('../../manager/frontend/src', import.meta.url)),
    },
  },
  build: {
    outDir: './dist',
    emptyOutDir: true,
    // Default hashed filenames on purpose: Cloudflare caches /admin/dist/* for
    // hours, so a fixed index.css name kept serving stale UI after every deploy.
  },
});
