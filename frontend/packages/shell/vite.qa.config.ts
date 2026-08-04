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

// QA-only Vite config — used when running end-to-end QA against an
// isolated SEP backend instance on a non-standard port.
// Parameterized via env vars so each parallel QA session can point at
// a different backend port without editing this file:
//
//   SEP_QA_BACKEND     URL of the running QA SEP instance
//                      (default 'http://127.0.0.1:18002')
//   SEP_QA_VITE_PORT   Port for this Vite dev server  (default 15174)
//
// `cookieDomainRewrite: 'localhost'` rewrites Set-Cookie domains from
// the backend's 127.0.0.1 to localhost so the browser persists the
// auth cookie (otherwise it's silently dropped on every request and
// the QA session expires after the access-token TTL).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const BACKEND = process.env.SEP_QA_BACKEND ?? 'http://127.0.0.1:18002';
const PORT = Number(process.env.SEP_QA_VITE_PORT || 15174);

const proxyEntry = {
  target: BACKEND,
  changeOrigin: true,
  cookieDomainRewrite: 'localhost',
};

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
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      'react-hook-form': path.resolve(__dirname, 'node_modules/react-hook-form'),
    },
  },
  server: {
    port: PORT,
    strictPort: true,
    proxy: {
      '/api': proxyEntry,
      '/sep_app': proxyEntry,
      '/legacy': proxyEntry,
      '/stream-logs': proxyEntry,
      '/execution-events': proxyEntry,
      '/files': proxyEntry,
      // App static mounts (snippets, dipper) and anonymous legacy Jinja assets
      // (see app/sep/main.py). Without this, SPA fallback returns index.html.
      '/static': proxyEntry,
    },
  },
  optimizeDeps: {
    include: ['@mui/material', '@emotion/react', '@emotion/styled', '@percona/percona-ui'],
  },
  ssr: {
    noExternal: ['@percona/percona-ui'],
  },
});
