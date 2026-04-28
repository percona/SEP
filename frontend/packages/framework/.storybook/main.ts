import type { StorybookConfig } from '@storybook/react-vite';
import { mergeConfig } from 'vite';

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.@(ts|tsx|mdx)'],
  addons: ['@storybook/addon-a11y'],
  framework: {
    name: '@storybook/react-vite',
    options: {},
  },
  typescript: {
    reactDocgen: 'react-docgen-typescript',
  },
  async viteFinal(viteConfig) {
    return mergeConfig(viteConfig, {
      resolve: {
        dedupe: [
          'react',
          'react-dom',
          '@mui/material',
          '@emotion/react',
          '@emotion/styled',
          'react-hook-form',
        ],
      },
      optimizeDeps: {
        include: ['@mui/material', '@emotion/react', '@emotion/styled', '@percona/percona-ui'],
      },
      ssr: {
        noExternal: ['@percona/percona-ui'],
      },
    });
  },
};

export default config;
