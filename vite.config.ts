import { defineConfig, type ProxyOptions } from 'vite'
import { sfcPlugin } from './vite-plugin-sfc'
import istanbul from 'vite-plugin-istanbul'
import os from 'os'

// Vite's proxy (http-proxy) leaves the browser's side of a response open when
// the backend's side closes early: a backend that restarts mid-stream leaves
// an event stream open and silent, so the browser never sees an error and
// never reconnects. Close it along with the backend's.
// https://github.com/chimurai/http-proxy-middleware/discussions/765
type ProxyServer = Parameters<NonNullable<ProxyOptions['configure']>>[0];
function closeWithBackend(proxy: ProxyServer) {
  proxy.on('proxyRes', (proxyRes, _req, res) => {
    proxyRes.on('close', () => {
      if (!res.writableEnded) res.destroy();
    });
  });
}

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
    // The page's console in this server's output, and so in var/log: every
    // level, and uncaught errors. Vite turns this on by itself only when it
    // thinks an AI agent started it, and then for warnings and errors only.
    forwardConsole: {
      unhandledErrors: true,
      logLevels: ['error', 'warn', 'info', 'log', 'debug'],
    },
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/agent': {
        target: `http://${localIP}:8999`,
        configure: (proxy) => {
          closeWithBackend(proxy);
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
        configure: closeWithBackend,
      },
      '/events': {
        target: `http://${localIP}:8999`,
        configure: (proxy) => {
          closeWithBackend(proxy);
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
