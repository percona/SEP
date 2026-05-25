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

import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { ReactNode } from 'react';

const { mockApiGet } = vi.hoisted(() => ({ mockApiGet: vi.fn() }));

vi.mock('@sep/api', async () => {
  const actual = await vi.importActual<typeof import('@sep/api')>('@sep/api');
  return {
    ...actual,
    apiClient: { get: mockApiGet },
  };
});

import { useTaskHistoryByNames } from './useTaskHistory';

const EMPTY_PAGE = {
  items: [],
  total: 0,
  offset: 0,
  limit: 0,
};

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiGet.mockResolvedValue({ data: EMPTY_PAGE });
});

describe('useTaskHistoryByNames', () => {
  it('does not call the API when taskNames is empty', () => {
    renderHook(() => useTaskHistoryByNames([]), { wrapper: wrapper() });
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it('does not call the API when enabled=false', () => {
    renderHook(() => useTaskHistoryByNames(['task-a'], { enabled: false }), {
      wrapper: wrapper(),
    });
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it('calls /api/sep/task-history/ with deduplicated sorted task_names', async () => {
    renderHook(() => useTaskHistoryByNames(['task-b', 'task-a', 'task-b']), {
      wrapper: wrapper(),
    });
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith('/sep/task-history/', {
        params: {
          task_names: ['task-a', 'task-b'],
        },
      });
    });
  });

  it('forwards status, offset, and limit query params', async () => {
    renderHook(
      () =>
        useTaskHistoryByNames(['task-a'], {
          status: 'running',
          offset: 5,
          limit: 10,
        }),
      { wrapper: wrapper() },
    );
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith('/sep/task-history/', {
        params: {
          status: 'running',
          offset: 5,
          limit: 10,
          task_names: ['task-a'],
        },
      });
    });
  });
});
