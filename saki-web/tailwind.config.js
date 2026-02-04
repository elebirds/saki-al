/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  // 核心配置：避免 Tailwind 覆盖 Antd 样式
  corePlugins: {
    preflight: false, 
  },
  plugins: [],
}
