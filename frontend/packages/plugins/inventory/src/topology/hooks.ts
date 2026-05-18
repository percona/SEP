/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { EventStreamContentType, fetchEventSource } from '@microsoft/fetch-event-source';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, emitUnauthorized, getToken, refreshAccessToken } from '@sep/api';
import type { TopologyCollectResponse, TopologyResultResponse, TopologyStreamEvent } from './types';

const TOPOLOGY_BASE = '/plugins/inventory/topology';

export const TOPOLOGY_RESULT_QUERY_KEY = 'inventory-topology-result';

function topologyStreamUrl(idsParam: string): string {
  return apiClient.getUri({
    url: `${TOPOLOGY_BASE}/stream`,
    params: { ids: idsParam },
  });
}

export interface CollectArgs {
  shards?: number;
  executor_host?: string;
  connect_timeout?: number;
  read_timeout?: number;
}

/**
 * Trigger a fresh topology collection. Returns the dispatched task history
 * ids; the caller wires those into `useTopologyResult` and
 * `useTopologyStream` for incremental updates.
 */
export function useCollectTopology() {
  const queryClient = useQueryClient();
  return useMutation<TopologyCollectResponse, Error, CollectArgs | undefined>({
    mutationFn: async (args) => {
      const { data } = await apiClient.post<TopologyCollectResponse>(
        `${TOPOLOGY_BASE}/collect`,
        args ?? {},
      );
      return data;
    },
    onSuccess: () => {
      // Force any /result query to re-evaluate against the new task ids.
      queryClient.invalidateQueries({ queryKey: [TOPOLOGY_RESULT_QUERY_KEY] });
    },
  });
}

/**
 * Poll /result until every dispatched task is finished. Long staleTime
 * keeps the cached graph hot across tab switches; manual refetch via the
 * UI Refresh button surfaces a fresh collection.
 */
export function useTopologyResult(taskHistoryIds: number[] | null) {
  const idsParam = useMemo(
    () => (taskHistoryIds && taskHistoryIds.length > 0 ? taskHistoryIds.join(',') : null),
    [taskHistoryIds],
  );
  return useQuery<TopologyResultResponse>({
    queryKey: [TOPOLOGY_RESULT_QUERY_KEY, idsParam],
    enabled: !!idsParam,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    queryFn: async () => {
      const { data } = await apiClient.get<TopologyResultResponse>(`${TOPOLOGY_BASE}/result`, {
        params: { ids: idsParam },
      });
      return data;
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) {
        return 2000;
      }
      return data.status === 'running' ? 2000 : false;
    },
    refetchOnWindowFocus: false,
  });
}

export interface TopologyStreamState {
  isStreaming: boolean;
  events: TopologyStreamEvent[];
  hostsCompleted: number;
  error: Error | null;
  /** Clear the current error. Used by the alert's dismiss button. */
  dismissError: () => void;
}

const NOOP = () => {
  // Replaced with a stable callback inside the hook body.
};

const INITIAL_STREAM_STATE: TopologyStreamState = {
  isStreaming: false,
  events: [],
  hostsCompleted: 0,
  error: null,
  dismissError: NOOP,
};

class TopologyStreamRetriableAfterRefresh extends Error {}

class TopologyStreamFatalError extends Error {}

/**
 * Open an SSE connection to /topology/stream and accumulate events.
 *
 * Uses fetch-based SSE so the SPA Bearer token can ride as an
 * Authorization header; native EventSource cannot send custom headers.
 */
export function useTopologyStream(
  taskHistoryIds: number[] | null,
  options?: { enabled?: boolean },
): TopologyStreamState {
  const dismissError = useCallback(() => {
    setState((prev) => (prev.error ? { ...prev, error: null } : prev));
  }, []);

  const [state, setState] = useState<TopologyStreamState>(() => ({
    ...INITIAL_STREAM_STATE,
    dismissError,
  }));
  const hostsCompletedRef = useRef(0);
  const enabled = options?.enabled ?? true;

  const idsParam = useMemo(
    () => (taskHistoryIds && taskHistoryIds.length > 0 ? taskHistoryIds.join(',') : null),
    [taskHistoryIds],
  );

  useEffect(() => {
    if (!enabled || !idsParam) {
      setState({ ...INITIAL_STREAM_STATE, dismissError });
      hostsCompletedRef.current = 0;
      return;
    }
    setState({ ...INITIAL_STREAM_STATE, dismissError, isStreaming: true });
    hostsCompletedRef.current = 0;

    const url = topologyStreamUrl(idsParam);
    const ctrl = new AbortController();
    const taskIds = idsParam.split(',').map((s) => Number(s));
    const openedAt = Date.now();
    let eventsReceived = 0;
    let completed = false;
    let terminalFailure = false;
    let disposed = false;
    let currentToken = getToken() ?? '';
    let refreshAttempted = false;

    const connectionLostError = () => {
      const elapsedSec = ((Date.now() - openedAt) / 1000).toFixed(1);
      const ids = taskIds.join(',');
      return new Error(
        `Topology stream connection lost for task(s) ${ids} ` +
          `after ${eventsReceived} event(s), ${elapsedSec}s elapsed.`,
      );
    };

    const setStreamError = (error: Error) => {
      setState((prev) => ({
        ...prev,
        isStreaming: false,
        error: prev.error ?? error,
      }));
    };

    const recordEvent = (event: TopologyStreamEvent) => {
      eventsReceived += 1;
      if (event.event === 'complete') {
        completed = true;
        ctrl.abort();
      }
      setState((prev) => {
        const events = [...prev.events, event];
        let hostsCompleted = prev.hostsCompleted;
        if (event.event === 'host_done' || event.event === 'host_error') {
          hostsCompletedRef.current += 1;
          hostsCompleted = hostsCompletedRef.current;
        }
        const isStreaming = event.event !== 'complete';
        return { ...prev, events, hostsCompleted, isStreaming };
      });
    };

    fetchEventSource(url, {
      signal: ctrl.signal,
      openWhenHidden: true,
      fetch: (input, init) => {
        const headers = new Headers(init?.headers as HeadersInit | undefined);
        if (currentToken) {
          headers.set('Authorization', `Bearer ${currentToken}`);
        }
        return globalThis.fetch(input as RequestInfo, { ...init, headers });
      },
      onopen: async (response) => {
        const contentType = response.headers.get('content-type') ?? '';
        if (response.ok && contentType.includes(EventStreamContentType)) {
          refreshAttempted = false;
          return;
        }
        let isAuthFailure = false;
        if (response.ok) {
          isAuthFailure = true;
        } else if (response.status === 401 && !refreshAttempted) {
          refreshAttempted = true;
          const newToken = await refreshAccessToken();
          if (newToken) {
            currentToken = newToken;
            throw new TopologyStreamRetriableAfterRefresh();
          }
          isAuthFailure = true;
        } else if (response.status === 401) {
          isAuthFailure = true;
        }
        if (isAuthFailure) {
          emitUnauthorized();
        }
        const message = response.ok
          ? `Topology stream endpoint returned non-SSE content: ${contentType || 'unknown'}`
          : `Topology stream open failed with status ${response.status}`;
        if (!disposed) {
          setStreamError(new Error(message));
        }
        terminalFailure = true;
        ctrl.abort();
        throw new TopologyStreamFatalError(message);
      },
      onmessage: (raw) => {
        if (disposed || !raw.data) {
          return;
        }
        try {
          const data = JSON.parse(raw.data);
          recordEvent({
            event: raw.event as TopologyStreamEvent['event'],
            data,
          } as TopologyStreamEvent);
        } catch (err) {
          // Malformed line — record as error but keep listening.
          setState((prev) => ({
            ...prev,
            error: err instanceof Error ? err : new Error('Malformed SSE payload'),
          }));
        }
      },
      onerror: (err): number | undefined => {
        if (err instanceof TopologyStreamRetriableAfterRefresh) {
          return 0;
        }
        if (err instanceof TopologyStreamFatalError) {
          throw err;
        }
        if (!disposed && !completed) {
          setStreamError(connectionLostError());
        }
        terminalFailure = true;
        ctrl.abort();
        throw new TopologyStreamFatalError('Topology stream connection lost');
      },
      onclose: () => {
        if (disposed || completed || terminalFailure) {
          return;
        }
        setStreamError(connectionLostError());
      },
    }).catch(() => {
      // Abort/fatal paths already updated state.
    });

    return () => {
      disposed = true;
      ctrl.abort();
    };
  }, [idsParam, enabled, dismissError]);

  return state;
}
