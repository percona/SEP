import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { federation } from '@module-federation/vite';

export default defineConfig({
  plugins: [
    react(),
    federation({
      name: 'micro-frontend-vite',
      filename: 'remoteEntry.js',
      manifest: true,
      exposes: { './RemoteButton': './src/RemoteButton.tsx', './MyTable': './src/MyTable.tsx'},
      shared: {
        react: { singleton: true, requiredVersion: '18.3.1' },
        'react-dom': { singleton: true, requiredVersion: '18.3.1' }
      }
    })
  ],
  server: {
    port: 3001,
  },
  build: { target: 'esnext', minify: false, cssCodeSplit: false }
});
