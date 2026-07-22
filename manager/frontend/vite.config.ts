/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5273,
    strictPort: true,
    // Same-origin dev proxy to the local manager backend. Keeps Origin as the
    // dev-server origin (matches the backend's allowed_origin) and forwards the
    // /events WebSocket. Only used in real API mode.
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_TARGET ?? 'http://127.0.0.1:8765',
        changeOrigin: false,
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    testTimeout: 15000,
  },
});
