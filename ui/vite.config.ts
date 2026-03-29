import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Proxy all /api HTTP requests to the FastAPI backend
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,  // also proxy WebSocket upgrades (events/live)
      },
    },
  },
})
