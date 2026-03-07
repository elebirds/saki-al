import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }
          const path = id.replace(/\\/g, '/')
          if (path.includes('/recharts/') || path.includes('/d3-')) {
            return 'vendor-charts'
          }
          if (path.includes('/konva/') || path.includes('/react-konva/')) {
            return 'vendor-konva'
          }
          if (path.includes('/i18next/') || path.includes('/react-i18next/')) {
            return 'vendor-i18n'
          }
          if (path.includes('/@zip.js/zip.js/')) {
            return 'vendor-zip'
          }
          return undefined
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
