import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forward API calls to the local FastAPI backend (backend/ directory).
    proxy: {
      '/api': {
        target: process.env.KRISHISYNC_API || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
