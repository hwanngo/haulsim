import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

// Dev server runs on :3000 and proxies API/SSE calls to the Litestar backend (:5001).
export default defineConfig({
  plugins: [
    react(),
    // Installable PWA: generates the web manifest + a Workbox service worker
    // (precaches the app shell) and auto-injects registration into index.html.
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'AMT Cycle Workbench',
        short_name: 'AMT Workbench',
        description: 'Turn AMT haul-truck telemetry into simulation files.',
        theme_color: '#FFCD11',
        background_color: '#f4f4f4',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        // Don't let the SW intercept the API/SSE — those must hit the backend live.
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  build: {
    // Never ship source maps in the production bundle — they would expose the
    // original source. `false` is Vite's default; set explicitly as a guard
    // against an accidental future flip.
    sourcemap: false,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
