import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const normalizeChunkName = (name: string): string => name.replace(/[^a-zA-Z0-9_-]/g, '-')
const skipManualChunkPackages = new Set(['dom-helpers', 'json2mq', 'string-convert'])

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
          const nodeModulesIndex = path.lastIndexOf('/node_modules/')
          const packagePath = nodeModulesIndex >= 0 ? path.slice(nodeModulesIndex + 14) : path
          const packageName = packagePath.startsWith('@')
            ? packagePath.split('/').slice(0, 2).join('/')
            : packagePath.split('/')[0]
          if (skipManualChunkPackages.has(packageName)) {
            return undefined
          }

          if (id.includes('react-dom') || id.includes('react-router') || id.includes('/react/')) {
            return 'vendor-react'
          }
          if (packageName === 'antd') {
            const componentName = normalizeChunkName(packagePath.split('/')[2] || 'core')
            if (componentName === 'index-js' || componentName === 'version' || componentName === 'row' || componentName === 'col') {
              return 'vendor-antd-core'
            }
            return `vendor-antd-${componentName}`
          }
          if (packageName === '@ant-design/icons' || packageName === '@ant-design/icons-svg') {
            return 'vendor-antd-icons'
          }
          if (packageName === '@ant-design/cssinjs' || packageName === '@ant-design/fast-color') {
            return 'vendor-antd-style'
          }
          if (packageName.startsWith('rc-')) {
            return `vendor-${packageName}`
          }
          if (id.includes('/recharts/') || id.includes('/d3-')) {
            return 'vendor-charts'
          }
          if (id.includes('/konva/') || id.includes('/react-konva/')) {
            return 'vendor-konva'
          }
          if (id.includes('/i18next/') || id.includes('/react-i18next/')) {
            return 'vendor-i18n'
          }
          return `vendor-${normalizeChunkName(packageName.replace('@', '').replace('/', '-'))}`
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
