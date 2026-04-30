// Temporary QA override — proxies to SEP-1053 QA instance
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import tsconfigPaths from 'vite-tsconfig-paths';
import path from 'path';

const BACKEND = 'http://127.0.0.1:18002';

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  resolve: {
    dedupe: [
      'react',
      'react-dom',
      '@mui/material',
      '@emotion/react',
      '@emotion/styled',
      'react-hook-form',
    ],
    alias: {
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      'react-hook-form': path.resolve(__dirname, 'node_modules/react-hook-form'),
    },
  },
  server: {
    port: 15174,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/sep_app': { target: BACKEND, changeOrigin: true },
      '/legacy': { target: BACKEND, changeOrigin: true },
    },
  },
  optimizeDeps: {
    include: ['@mui/material', '@emotion/react', '@emotion/styled', '@percona/percona-ui'],
  },
  ssr: {
    noExternal: ['@percona/percona-ui'],
  },
});
