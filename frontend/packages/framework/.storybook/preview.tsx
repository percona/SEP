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

import CssBaseline from '@mui/material/CssBaseline';
import { ThemeContextProvider, sepThemeOptions } from '@percona/percona-ui';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Preview } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router';
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
