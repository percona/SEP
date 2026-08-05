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
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useCheckServiceConnectivity, useRefreshEntitiesOnSyncComplete } from './hooks';

const ENTITY_ROOT_KEY = ['plugins', 'inventory', 'entity'];

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { invalidate, wrapper };
}

describe('useRefreshEntitiesOnSyncComplete', () => {
  afterEach(() => vi.restoreAllMocks());

  it('invalidates the entity list exactly once on the is_running true → false edge', () => {
    const { invalidate, wrapper } = setup();
    const { rerender } = renderHook(
      (isRunning: boolean | undefined) => useRefreshEntitiesOnSyncComplete(isRunning),
      {
        wrapper,
        initialProps: true as boolean | undefined,
      },
    );

    expect(invalidate).not.toHaveBeenCalled();

    rerender(false);

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ENTITY_ROOT_KEY });
  });

  it('does not invalidate on initial mount when idle (no prior running state)', () => {
    const { invalidate, wrapper } = setup();
    renderHook(() => useRefreshEntitiesOnSyncComplete(false), { wrapper });

    expect(invalidate).not.toHaveBeenCalled();
  });

  it('does not invalidate while the sync stays running (repeated polls)', () => {
    const { invalidate, wrapper } = setup();
    const { rerender } = renderHook(
      (isRunning: boolean | undefined) => useRefreshEntitiesOnSyncComplete(isRunning),
      {
        wrapper,
        initialProps: true as boolean | undefined,
      },
    );

    rerender(true);
    rerender(true);

    expect(invalidate).not.toHaveBeenCalled();
  });

  it('does not treat the first loaded status (undefined → false) as a transition', () => {
    const { invalidate, wrapper } = setup();
    const { rerender } = renderHook(
      (isRunning: boolean | undefined) => useRefreshEntitiesOnSyncComplete(isRunning),
      {
        wrapper,
        initialProps: undefined as boolean | undefined,
      },
    );

    rerender(false);

    expect(invalidate).not.toHaveBeenCalled();
  });

  it('fires again on a second sync cycle', () => {
    const { invalidate, wrapper } = setup();
    const { rerender } = renderHook(
      (isRunning: boolean | undefined) => useRefreshEntitiesOnSyncComplete(isRunning),
      {
        wrapper,
        initialProps: false as boolean | undefined,
      },
    );

    rerender(true);
    rerender(false);
    expect(invalidate).toHaveBeenCalledTimes(1);

    rerender(true);
    rerender(false);
    expect(invalidate).toHaveBeenCalledTimes(2);
  });

  it('cascades to a nested entity-list query via root-key prefix match', async () => {
    // Guard against the duplicated root-key literal drifting out of the shape
    // useAppEntityList actually keys lists by: seed a real node-list query
    // and assert the true → false edge marks it invalidated through the prefix.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const NODE_LIST_KEY = ['plugins', 'inventory', 'entity', 'nodes'];
    client.setQueryData(NODE_LIST_KEY, [{ id: 1 }]);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { rerender } = renderHook(
      (isRunning: boolean | undefined) => useRefreshEntitiesOnSyncComplete(isRunning),
      { wrapper, initialProps: true as boolean | undefined },
    );

    rerender(false);

    await waitFor(() => {
      expect(client.getQueryState(NODE_LIST_KEY)?.isInvalidated).toBe(true);
    });
  });
});

describe('useCheckServiceConnectivity', () => {
  afterEach(() => vi.restoreAllMocks());

  function setupMutation(serviceId: string | number) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    return renderHook(() => useCheckServiceConnectivity(serviceId), { wrapper });
  }

  it('posts to the service-scoped endpoint and returns the probe body', async () => {
    const body = { success: false, error: 'Connection refused', task_history_id: 12 };
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: body } as never);

    const { result } = setupMutation(42);
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postSpy).toHaveBeenCalledWith('/apps/inventory/services/42/check-connectivity/', {});
    expect(result.current.data).toEqual(body);
  });

  it('does not invalidate cached queries — a probe mutates no server state', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue();
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { success: true, error: null, task_history_id: 1 },
    } as never);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useCheckServiceConnectivity(42), { wrapper });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).not.toHaveBeenCalled();
  });
});
