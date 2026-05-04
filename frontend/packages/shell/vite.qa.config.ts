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
      '/stream-logs': { target: BACKEND, changeOrigin: true },
      '/execution-events': { target: BACKEND, changeOrigin: true },
    },
  },
  optimizeDeps: {
    include: ['@mui/material', '@emotion/react', '@emotion/styled', '@percona/percona-ui'],
  },
  ssr: {
    noExternal: ['@percona/percona-ui'],
  },
});
