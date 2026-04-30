import CssBaseline from '@mui/material/CssBaseline';
import { ThemeContextProvider, sepThemeOptions } from '@percona/percona-ui';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Preview } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router-dom';
import { apiClient } from '@sep/api';
import {
  installStorybookSseMocks,
  registerFetchResponse,
  registerSseScript,
  type StoryEventSource,
} from './sseMocks';

installStorybookSseMocks();

// Route axios through the global `fetch` so stories can stub responses via
// `parameters.fetchResponses`. Without this, axios uses its XHR adapter
// in the browser and bypasses the storybook fetch wrapper entirely.
apiClient.defaults.adapter = 'fetch';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
});

export type SseScriptMap = Record<string, (es: StoryEventSource) => void>;
export type FetchResponseMap = Record<string, unknown>;

declare module 'storybook/internal/types' {
  interface Parameters {
    sseScripts?: SseScriptMap;
    fetchResponses?: FetchResponseMap;
  }
}

const preview: Preview = {
  parameters: {
    controls: {
      matchers: { color: /(background|color)$/i, date: /Date$/i },
    },
    a11y: { test: 'todo' },
  },
  decorators: [
    (Story, context) => {
      const sseScripts = (context.parameters.sseScripts ?? {}) as SseScriptMap;
      const fetchResponses = (context.parameters.fetchResponses ?? {}) as FetchResponseMap;
      for (const [url, script] of Object.entries(sseScripts)) {
        registerSseScript(url, script);
      }
      for (const [prefix, body] of Object.entries(fetchResponses)) {
        registerFetchResponse(prefix, body);
      }

      return (
        <QueryClientProvider client={queryClient}>
          <ThemeContextProvider themeOptions={sepThemeOptions}>
            <CssBaseline />
            <MemoryRouter>
              <Story />
            </MemoryRouter>
          </ThemeContextProvider>
        </QueryClientProvider>
      );
    },
  ],
};

export default preview;
