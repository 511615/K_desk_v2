import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  test: {
    include: ['src/**/*.spec.ts'],
    exclude: ['e2e/**'],
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8877',
      '/download': 'http://127.0.0.1:8877',
      '/chart-file': 'http://127.0.0.1:8877',
    },
  },
})
