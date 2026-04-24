import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import tsconfigPaths from 'vite-tsconfig-paths';
import path from 'path';

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
      // Force all workspace packages to use the same instances
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      'react-hook-form': path.resolve(__dirname, 'node_modules/react-hook-form'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/sep_app': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/legacy': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/stream-logs': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/execution-events': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    include: ['@mui/material', '@emotion/react', '@emotion/styled', '@percona/percona-ui'],
  },
  ssr: {
    // Inline percona-ui so Vite can process its ESM properly (same as PMM)
    noExternal: ['@percona/percona-ui'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (
            id.includes('/node_modules/react/') ||
            id.includes('/node_modules/react-dom/') ||
            id.includes('/node_modules/react-router-dom/')
          ) {
            return 'vendor-react';
          }
          if (
            id.includes('/node_modules/@mui/material/') ||
            id.includes('/node_modules/@mui/icons-material/')
          ) {
            return 'vendor-mui';
          }
          if (
            id.includes('/node_modules/@emotion/react/') ||
            id.includes('/node_modules/@emotion/styled/')
          ) {
            return 'vendor-emotion';
          }
          if (
            id.includes('/node_modules/@percona/percona-ui/') ||
            id.includes('/node_modules/material-react-table/')
          ) {
            return 'vendor-percona';
          }
          if (id.includes('/node_modules/@tanstack/react-query/')) {
            return 'vendor-query';
          }
        },
      },
    },
  },
});
