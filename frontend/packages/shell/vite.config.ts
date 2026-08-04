/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
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
      // Task log SSE and related routes live outside /api (see app/sep/main.py).
      '/stream-logs': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/execution-events': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/files': {
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
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (
            id.includes('/node_modules/react/') ||
            id.includes('/node_modules/react-dom/') ||
            id.includes('/node_modules/react-router/')
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
