import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import federation from '@originjs/vite-plugin-federation';

export default defineConfig({
  plugins: [
    react(),
    federation({
      name: 'micro-frontend',
      filename: 'remoteEntry.js', // This is the file that the host will load
      exposes: {
        './App': './src/App.jsx', // Expose the main App component
      },
      shared: ['react', 'react-dom'], // Share common dependencies to avoid duplication
    }),
  ],
  // This is important for Module Federation to work correctly.
  build: {
    target: 'esnext',
    minify: false,
    cssCodeSplit: false,
  },
  server: {
    // This port should be different from the FastAPI port
    port: 5001,
  },
});

