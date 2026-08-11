import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
import { brandColors } from './scripts/tokenColors.mjs'

/**
 * The API port is configurable because 8000 is not always free — VS Code claims it on some
 * machines. `KINDRED_API_PORT` overrides; the default matches the port the server is
 * documented to run on locally.
 */
const apiPort = process.env.KINDRED_API_PORT ?? '8010'
const apiTarget = `http://localhost:${apiPort}`

/**
 * The manifest's two colours are read from the design tokens at build time. A manifest is
 * static JSON and cannot reference a custom property, so this is the sanctioned place a
 * literal colour is emitted — generated, never hand-typed.
 */
const colors = brandColors()

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      // Same rule as the manifest: <meta name="theme-color"> needs a literal, so it is
      // substituted from the token rather than written into the HTML.
      name: 'kindred:theme-color',
      transformIndexHtml(html) {
        return html.replaceAll('__THEME_COLOR__', colors.accent)
      },
    },
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      includeAssets: ['favicon.svg', 'icons/apple-touch-icon-180.png'],
      manifest: {
        name: 'Kindred',
        short_name: 'Kindred',
        description: 'Plan a family holiday together — suggestions, votes and one itinerary.',
        start_url: '/?source=pwa',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait-primary',
        theme_color: colors.accent,
        background_color: colors.background,
        categories: ['travel', 'productivity'],
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          {
            src: '/icons/icon-512-maskable.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // The app shell only: markup, code, styles, the wordmark face and the icons.
        // Nothing under /api is precached or runtime-cached — a trip plan that silently
        // serves yesterday's answer is worse than one that says it is offline.
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/ws$/],
      },
      // The service worker is off in dev so a stale cache can never explain a bug.
      devOptions: { enabled: false },
    }),
  ],
  server: {
    proxy: {
      // F-2: the dev server proxies the API and the socket to a locally running uvicorn,
      // which also makes the session cookie same-origin in development.
      '/api': { target: apiTarget, changeOrigin: true },
      '/ws': { target: apiTarget.replace('http', 'ws'), ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    css: true,
    setupFiles: ['./src/test/setup.ts'],
    // Playwright owns e2e/ (`npm run e2e`); its *.spec.ts files match vitest's default
    // glob but cannot be collected by it, and every vitest run would report them as
    // failed files — noise that would eventually hide a real failure.
    exclude: ['node_modules/**', 'e2e/**'],
  },
})
