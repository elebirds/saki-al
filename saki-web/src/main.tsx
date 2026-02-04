import React from 'react'
import ReactDOM from 'react-dom/client'
import { message } from 'antd'
import App from './App.tsx'
import { ThemeProvider } from './components/ThemeProvider'
import './index.css'
import './i18n'

// 全局错误处理：捕获未处理的 Promise rejection
window.addEventListener('unhandledrejection', (event) => {
  // 阻止默认的错误处理（控制台输出）
  event.preventDefault()
  
  // 提取错误消息
  let errorMessage = 'An unexpected error occurred'
  
  if (event.reason) {
    // 如果是 Error 对象，提取 message
    if (event.reason instanceof Error) {
      errorMessage = event.reason.message || errorMessage
    } 
    // 如果是字符串
    else if (typeof event.reason === 'string') {
      errorMessage = event.reason
    }
    // 如果是对象，尝试提取 message 或 detail
    else if (typeof event.reason === 'object') {
      errorMessage = event.reason.message || event.reason.detail || errorMessage
    }
  }
  
  // 显示错误提示
  message.error(errorMessage)
  
  // 不再输出到控制台，避免重复日志
})

  // 全局错误处理：捕获未处理的 JavaScript 错误
  window.addEventListener('error', (event) => {
    // 对于某些错误，我们可能不想显示提示（比如资源加载错误）
    if (event.error) {
      const errorMessage = event.error.message || event.message || 'An unexpected error occurred'
      message.error(errorMessage)
      
      // 不再输出到控制台，避免重复日志
    }
  })

ReactDOM.createRoot(document.getElementById('root')!).render(
  //<React.StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  //</React.StrictMode>,
)
