/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // The FastAPI service (make api). Proxied so the browser sees one origin and the
  // API needs no CORS. Set API_URL if it runs somewhere other than localhost:8000.
  const target = loadEnv(mode, '.', '').API_URL || 'http://127.0.0.1:8000'
  const proxy = { '/api': { target } }
  return {
    plugins: [react()],
    server: { proxy },
    preview: { proxy },
    test: { environment: 'node', include: ['src/**/*.test.ts'] },
  }
})
