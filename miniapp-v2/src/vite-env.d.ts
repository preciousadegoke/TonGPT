/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_TONCONNECT_MANIFEST_URL?: string;
  readonly VITE_TON_NETWORK?: 'mainnet' | 'testnet';
  readonly VITE_BOT_USERNAME?: string;
  readonly VITE_DEV_API_PROXY?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
