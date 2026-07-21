/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: 'mock' | 'real';
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_WS_URL?: string;
  readonly VITE_LOCAL_TOKEN?: string;
  readonly VITE_AUTH_BG_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  __CLOAKBROWSER__?: {
    token?: string;
    apiBaseUrl?: string;
    wsUrl?: string;
  };
}
