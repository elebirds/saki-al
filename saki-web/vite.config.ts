import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const ANTD_FORM_COMPONENTS = new Set([
  'auto-complete',
  'cascader',
  'checkbox',
  'color-picker',
  'date-picker',
  'form',
  'input',
  'input-number',
  'mentions',
  'radio',
  'select',
  'slider',
  'switch',
  'time-picker',
  'tree-select',
  'upload',
])

const ANTD_DATA_COMPONENTS = new Set([
  'card',
  'collapse',
  'descriptions',
  'drawer',
  'list',
  'menu',
  'message',
  'modal',
  'notification',
  'pagination',
  'popover',
  'progress',
  'result',
  'steps',
  'table',
  'tabs',
  'tooltip',
  'tree',
])

const RC_FORM_PACKAGES = new Set([
  'rc-cascader',
  'rc-field-form',
  'rc-input',
  'rc-input-number',
  'rc-mentions',
  'rc-picker',
  'rc-select',
  'rc-slider',
  'rc-switch',
  'rc-textarea',
  'rc-tree-select',
  'rc-upload',
])

const RC_DATA_PACKAGES = new Set([
  'rc-collapse',
  'rc-dialog',
  'rc-drawer',
  'rc-menu',
  'rc-notification',
  'rc-pagination',
  'rc-steps',
  'rc-table',
  'rc-tabs',
  'rc-tooltip',
  'rc-tree',
  'rc-virtual-list',
])

const getPackageName = (path: string): string | undefined => {
  const nodeModulesIndex = path.lastIndexOf('/node_modules/')
  if (nodeModulesIndex < 0) {
    return undefined
  }
  const packagePath = path.slice(nodeModulesIndex + 14)
  if (packagePath.startsWith('@')) {
    return packagePath.split('/').slice(0, 2).join('/')
  }
  return packagePath.split('/')[0]
}

const resolveAntdChunk = (path: string, packageName: string): string => {
  if (packageName === 'antd') {
    const packagePath = path.slice(path.lastIndexOf('/node_modules/') + 14)
    const componentName = packagePath.split('/')[2] || 'core'
    if (ANTD_FORM_COMPONENTS.has(componentName)) {
      return 'vendor-antd-form'
    }
    if (ANTD_DATA_COMPONENTS.has(componentName)) {
      return 'vendor-antd-data'
    }
    return 'vendor-antd-core'
  }
  if (packageName.startsWith('rc-')) {
    if (RC_FORM_PACKAGES.has(packageName)) {
      return 'vendor-antd-form'
    }
    if (RC_DATA_PACKAGES.has(packageName)) {
      return 'vendor-antd-data'
    }
    return 'vendor-antd-core'
  }
  return 'vendor-antd-core'
}

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
          const packageName = getPackageName(path)
          if (!packageName) {
            return undefined
          }

          if (path.includes('/react-dom/') || path.includes('/react-router/') || path.includes('/react/')) {
            return 'vendor-react'
          }
          if (path.includes('/recharts/') || path.includes('/d3-')) {
            return 'vendor-charts'
          }
          if (path.includes('/konva/') || path.includes('/react-konva/')) {
            return 'vendor-konva'
          }
          if (path.includes('/i18next/') || path.includes('/react-i18next/')) {
            return 'vendor-i18n'
          }
          if (packageName === '@ant-design/icons' || packageName === '@ant-design/icons-svg') {
            return 'vendor-antd-icons'
          }
          if (packageName === 'antd' || packageName.startsWith('rc-') || packageName.startsWith('@ant-design/')) {
            return resolveAntdChunk(path, packageName)
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
