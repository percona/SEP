import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react-swc';
import tsconfigPaths from 'vite-tsconfig-paths';
import path from 'path';

/**
 * percona-ui inlines react-hook-form and creates its own React context for
 * useFormContext(). When no FormProvider wraps the tree the context is null,
 * causing `const { control } = useFormContext()` to throw — even though
 * every input also accepts an explicit `control` prop as fallback.
 *
 * This plugin patches the pre-bundled percona-ui code so the destructure
 * tolerates a null context (falls back to empty object), letting the
 * explicit `control` prop work as intended.
 */
function perconaUiFormContextPatch(): Plugin {
  return {
    name: 'percona-ui-form-context-patch',
    transform(code, id) {
      if (!id.includes('@percona') && !id.includes('percona-ui')) return;
      // Replace destructures of the form context that crash on null:
      //   const { control: s } = mo()       → const { control: s } = mo() || {}
      //   const { control: s, formState ... } = mo() → same with || {}
      if (code.includes('mo()')) {
        return code.replace(/=\s*mo\(\)/g, '= (mo() || {})');
      }
    },
  };
}

export default defineConfig({
  plugins: [perconaUiFormContextPatch(), react(), tsconfigPaths()],
  resolve: {
    dedupe: ['react', 'react-dom', '@mui/material', '@emotion/react', '@emotion/styled', 'react-hook-form'],
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
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-mui': ['@mui/material', '@mui/icons-material'],
          'vendor-emotion': ['@emotion/react', '@emotion/styled'],
          'vendor-percona': ['@percona/percona-ui', 'material-react-table'],
          'vendor-query': ['@tanstack/react-query'],
        },
      },
    },
  },
});
