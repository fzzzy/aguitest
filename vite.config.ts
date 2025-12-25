import { defineConfig } from 'vite'
import { sfcPlugin } from './vite-plugin-sfc'

export default defineConfig({
  plugins: [sfcPlugin()],
  root: 'src',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/agent': 'http://127.0.0.1:8999',
      '/events': 'http://127.0.0.1:8999'
    }
  }
})
