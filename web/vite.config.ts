import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Phase 7 (`plan/features/foundation/tasks.md`) wires `vite-plugin-pwa` here with the
// manifest, icons and service-worker registration. The dependency is installed already so
// that step is a config change only.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // F-2: dev server proxies the API and the socket to a locally running uvicorn.
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    css: true,
  },
})
