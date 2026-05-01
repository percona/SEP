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

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useExecutionEvents } from '../../../hooks/useExecutionEvents';
import { installMockEventSource, MockEventSource } from '../../../../tests/eventSourceStub';

function createClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function makeWrapper(client: QueryClient) {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('useExecutionEvents', () => {
  beforeEach(() => {
    installMockEventSource();
  });

  afterEach(() => {
    MockEventSource.reset();
    vi.unstubAllGlobals();
  });

  describe('running tasks (SSE)', () => {
    it('opens an EventSource against /stream-logs/{id}/execution-events with credentials', () => {
      const wrapper = makeWrapper(createClient());
      renderHook(() => useExecutionEvents(42, true), { wrapper });

      expect(MockEventSource.instances).toHaveLength(1);
      expect(MockEventSource.instances[0].url).toBe('/stream-logs/42/execution-events');
      expect(MockEventSource.instances[0].withCredentials).toBe(true);
    });

    it('accumulates events and groups them by step', () => {
      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];

      act(() => {
        src.emitMessage({
          timestamp: 't1',
          type: 'started',
          description: 'A',
          step: 'setup',
        });
        src.emitMessage({
          timestamp: 't2',
          type: 'progress',
          description: 'B',
          step: 'setup',
        });
        src.emitMessage({ timestamp: 't3', type: 'started', description: 'C', step: 'test' });
      });

      expect(result.current.events).toHaveLength(3);
      expect(result.current.stepOrder).toEqual(['setup', 'test']);
      expect(result.current.eventsByStep.setup).toHaveLength(2);
      expect(result.current.eventsByStep.test).toHaveLength(1);
    });

    it('dedupes events with the same composite key', () => {
      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];

      const ev = { timestamp: 't', type: 'started', description: 'A', step: 'x' };
      act(() => {
        src.emitMessage(ev);
        src.emitMessage(ev); // duplicate
        src.emitMessage({ ...ev, description: 'B' }); // different description = new key
      });

      expect(result.current.events).toHaveLength(2);
    });

    it('buckets events without a step under the stepless key', () => {
      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];

      act(() => {
        src.emitMessage({ timestamp: 't1', type: 'started', description: 'A' });
        src.emitMessage({ timestamp: 't2', type: 'started', description: 'B', step: null });
      });

      expect(result.current.stepOrder).toEqual(['']);
      expect(result.current.eventsByStep['']).toHaveLength(2);
    });

    it('handles finish by stopping loading and closing the stream', () => {
      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];

      act(() => {
        src.emitNamed('finish', { status: 'success' });
      });

      expect(result.current.isLoading).toBe(false);
      expect(src.closed).toBe(true);
    });

    it('handles sep-error by setting error and closing the stream', () => {
      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];

      act(() => {
        src.emitNamed('sep-error', { code: 500, detail: 'boom' });
      });

      expect(result.current.error).toEqual({ code: 500, detail: 'boom' });
      expect(src.closed).toBe(true);
    });

    it('surfaces a terminal error when the stream closes via onerror', () => {
      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];

      act(() => {
        src.readyState = MockEventSource.CLOSED;
        src.onerror?.(new Event('error'));
      });

      expect(result.current.error).toBeDefined();
    });

    it('closes the EventSource on unmount', () => {
      const wrapper = makeWrapper(createClient());
      const { unmount } = renderHook(() => useExecutionEvents(1, true), { wrapper });
      const src = MockEventSource.instances[0];
      unmount();
      expect(src.closed).toBe(true);
    });
  });

  describe('completed tasks (REST)', () => {
    it('fetches /execution-events/{id} with credentials and surfaces events', async () => {
      const fetchSpy = vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve([
              { timestamp: 't1', type: 'started', description: 'A', step: 'setup' },
              { timestamp: 't2', type: 'completed', description: 'B', step: 'setup' },
            ]),
        }),
      );
      vi.stubGlobal('fetch', fetchSpy);

      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(7, false), { wrapper });

      await waitFor(() => expect(result.current.events).toHaveLength(2));
      expect(fetchSpy).toHaveBeenCalledWith(
        '/execution-events/7',
        expect.objectContaining({ credentials: 'include' }),
      );
      expect(result.current.stepOrder).toEqual(['setup']);
      // SSE must not have been opened
      expect(MockEventSource.instances).toHaveLength(0);
    });

    it('surfaces an error when the REST response is not ok', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(() => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) })),
      );

      const wrapper = makeWrapper(createClient());
      const { result } = renderHook(() => useExecutionEvents(7, false), { wrapper });

      await waitFor(() => expect(result.current.error).toBeDefined());
      expect(result.current.events).toEqual([]);
    });

    it('does not fetch when taskHistoryId is missing', () => {
      const fetchSpy = vi.fn(() =>
        Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) }),
      );
      vi.stubGlobal('fetch', fetchSpy);

      const wrapper = makeWrapper(createClient());
      renderHook(() => useExecutionEvents(undefined, false), { wrapper });

      expect(fetchSpy).not.toHaveBeenCalled();
      expect(MockEventSource.instances).toHaveLength(0);
    });
  });

  describe('transition', () => {
    it('switches from SSE to REST when isRunning flips to false', async () => {
      const fetchSpy = vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve([
              { timestamp: 't-final', type: 'completed', description: 'done', step: 'x' },
            ]),
        }),
      );
      vi.stubGlobal('fetch', fetchSpy);

      const wrapper = makeWrapper(createClient());
      const { rerender, result } = renderHook(
        ({ running }: { running: boolean }) => useExecutionEvents(9, running),
        { wrapper, initialProps: { running: true } },
      );

      const src = MockEventSource.instances[0];
      expect(src).toBeDefined();

      rerender({ running: false });

      expect(src.closed).toBe(true);
      await waitFor(() => expect(result.current.events).toHaveLength(1));
      expect(fetchSpy).toHaveBeenCalledWith(
        '/execution-events/9',
        expect.objectContaining({ credentials: 'include' }),
      );
    });
  });
});
