import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// backend/ or mock_backend/: uv run uvicorn app.main:app --reload --port 8000 (API_PROXY=… for another port)
const API = process.env.API_PROXY ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // The OurSport API v1 (ws: true also proxies the live WebSockets under /api/v1/live/…)
      // and the health checks. Same origin keeps the session cookies first-party.
      '/api': { target: API, ws: true },
      '/health': { target: API },
      '/mock/': { target: API }, // mock_backend only: the magic-link outbox and demo scorer passes
      // ---- older mock-only publisher routes not yet on v1 -----------------------------------
      '^/tournaments(/|$)': { target: API },
      '^/review-queue(\\?.*)?$': { target: API },
      '^/review-queue/[^/]+(/claim)?(\\?.*)?$': { target: API },
      '^/stories(\\?.*)?$': { target: API },
      '^/stories/[^/]+/(check|approve|reject|regenerate|unpublish)$': { target: API },
      // /stories/{id} is also a fan page: only the editor's PATCH goes to the backend
      '^/stories/[^/]+$': { target: API, bypass: (req) => (req.method !== 'PATCH' ? req.url : undefined) },
      // /publisher/events is also a portal page: only API calls (not page loads) go to the backend
      '^/publisher/events$': {
        target: API,
        bypass: (req) => (req.method === 'GET' && req.headers.accept?.includes('text/html') ? req.url : undefined),
      },
      '^/uploads(/|$)': { target: API },
    },
  },
})
