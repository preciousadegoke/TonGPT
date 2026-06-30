import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { VitePWA } from 'vite-plugin-pwa';
import { fileURLToPath, URL } from 'node:url';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  // Map "@/..." to "src/..." for the bundler. tsconfig `paths` only covers
  // type-checking; Rollup needs this alias to actually resolve the imports.
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  plugins: [
    preact(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['logo.png'],
      manifest: {
        name: 'TonGPT',
        short_name: 'TonGPT',
        theme_color: '#0098EA',
        background_color: '#000000',
        display: 'standalone',
        icons: [{ src: 'logo.png', sizes: '512x512', type: 'image/png' }],
      },
      workbox: {
        // Cache the app shell + static API GETs for offline-friendly UX.
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'tongpt-api',
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 60, maxAgeSeconds: 300 },
            },
          },
        ],
      },
    }),
  ],
  build: {
    target: 'es2020',
    minify: 'terser',
    sourcemap: mode !== 'production',
    rollupOptions: {
      output: {
        // Split the heavy wallet SDK out of the main bundle so first paint is fast.
        manualChunks: {
          tonconnect: ['@tonconnect/ui'],
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    // Proxy API calls to the FastAPI backend during local dev.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_PROXY || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}));
