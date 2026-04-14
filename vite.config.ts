import { defineConfig } from 'vite'
import { sfcPlugin } from './vite-plugin-sfc'
import istanbul from 'vite-plugin-istanbul'
import os from 'os'

function getLocalIP(): string {
  const interfaces = os.networkInterfaces()
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name] || []) {
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address
      }
    }
  }
  return '127.0.0.1'
}

const localIP = getLocalIP()

export default defineConfig({
  plugins: [
    sfcPlugin(),
    istanbul({
      include: 'src/*',
      exclude: ['node_modules', 'test/'],
      extension: ['.js', '.ts', '.vue'],
      requireEnv: false
    })
  ],
  root: 'src',
  define: {
    'process.env': {},
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/agent': {
        target: `http://${localIP}:8999`,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            console.log(`[Proxy] ${req.method} ${req.url} -> ${localIP}:8999`);
          });
          proxy.on('error', (err, req) => {
            console.error(`[Proxy] Error for ${req.url}:`, err.message);
          });
        }
      },
      '/memes': {
        target: `http://${localIP}:8999`,
      },
      '/events': {
        target: `http://${localIP}:8999`,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            console.log(`[Proxy] ${req.method} ${req.url} -> ${localIP}:8999`);
          });
          proxy.on('error', (err, req) => {
            console.error(`[Proxy] Error for ${req.url}:`, err.message);
          });
        }
      }
    }
  }
})
