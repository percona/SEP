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

import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { apiClient } from '@sep/api';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useTasksList } from './hooks';
import { TASKS_PLUGINS_API_BASE } from './types';

interface CapturedRequestConfig {
  url?: string;
  method?: string;
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const originalAdapter = apiClient.defaults.adapter;

describe('useTasksList', () => {
  let lastConfig: CapturedRequestConfig | null = null;

  beforeEach(() => {
    lastConfig = null;
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = (
      config: CapturedRequestConfig,
    ) => {
      lastConfig = config;
      return Promise.resolve({
        data: [
          {
            name: 'monitor-task',
            backend: 'nomad',
            created_at: '2026-05-19T12:00:00Z',
            created_by: 'creator',
            last_updated_by: null,
          },
        ],
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
        request: {},
      });
    };
  });

  afterEach(() => {
    (apiClient.defaults as unknown as { adapter: unknown }).adapter = originalAdapter;
  });

  it('fetches task rows from the tasks plugin list endpoint', async () => {
    const { result } = renderHook(() => useTasksList(), { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(lastConfig?.url).toBe(`${TASKS_PLUGINS_API_BASE}/`);
    expect(result.current.data).toEqual([
      {
        name: 'monitor-task',
        backend: 'nomad',
        created_at: '2026-05-19T12:00:00Z',
        created_by: 'creator',
        last_updated_by: null,
      },
    ]);
  });

  it('does not fetch when disabled', async () => {
    const { result } = renderHook(() => useTasksList({ enabled: false }), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.fetchStatus).toBe('idle');
    });

    expect(lastConfig).toBeNull();
    expect(result.current.data).toBeUndefined();
  });
});
