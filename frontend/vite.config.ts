import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8877',
      '/download': 'http://127.0.0.1:8877',
      '/chart-file': 'http://127.0.0.1:8877',
    },
  },
})
