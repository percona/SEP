/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@sep/api';
import type { TopologyCollectResponse, TopologyResultResponse, TopologyStreamEvent } from './types';

const TOPOLOGY_BASE = '/plugins/inventory/topology';

export const TOPOLOGY_RESULT_QUERY_KEY = 'inventory-topology-result';

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

/**
 * Open an SSE connection to /topology/stream and accumulate events.
 *
 * The browser's `EventSource` does not support custom headers, so the
 * backend must serve the stream off the same origin via cookie auth or
 * a Bearer token forwarded another way. The stream is read-only and
 * disconnects automatically when the component unmounts or the task ids
 * change.
 *
 * On `event: complete` we close the EventSource ourselves and remember
 * that completion happened so the inevitable post-close `onerror`
 * (which fires because the server-side response ends) does not surface
 * a misleading "connection lost" alert. Real `onerror` events still
 * record an error message that includes the task history ids and how
 * many events / how much wall time we got before the drop, so the
 * user has enough context to either inspect the task history directly
 * or re-run the collection.
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

    const url = `/api${TOPOLOGY_BASE}/stream?ids=${encodeURIComponent(idsParam)}`;
    const source = new EventSource(url, { withCredentials: true });

    const taskIds = idsParam.split(',').map((s) => Number(s));
    const openedAt = Date.now();
    let eventsReceived = 0;
    let completed = false;

    const recordEvent = (event: TopologyStreamEvent) => {
      eventsReceived += 1;
      if (event.event === 'complete') {
        completed = true;
        source.close();
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

    const wireEvent = <K extends TopologyStreamEvent['event']>(name: K) => {
      const handler = (raw: MessageEvent) => {
        try {
          const data = JSON.parse(raw.data);
          recordEvent({ event: name, data } as TopologyStreamEvent);
        } catch (err) {
          // Malformed line — record as error but keep listening.
          setState((prev) => ({
            ...prev,
            error: err instanceof Error ? err : new Error('Malformed SSE payload'),
          }));
        }
      };
      source.addEventListener(name, handler);
      return () => source.removeEventListener(name, handler);
    };

    const removers: Array<() => void> = [
      wireEvent('ready'),
      wireEvent('task_status'),
      wireEvent('host_done'),
      wireEvent('host_error'),
      wireEvent('task_error'),
      wireEvent('task_done'),
      wireEvent('complete'),
    ];

    source.onerror = () => {
      if (completed) {
        return;
      }
      const elapsedSec = ((Date.now() - openedAt) / 1000).toFixed(1);
      const ids = taskIds.join(',');
      setState((prev) => ({
        ...prev,
        isStreaming: false,
        error:
          prev.error ??
          new Error(
            `Topology stream connection lost for task(s) ${ids} ` +
              `after ${eventsReceived} event(s), ${elapsedSec}s elapsed.`,
          ),
      }));
      source.close();
    };

    return () => {
      for (const remove of removers) {
        remove();
      }
      source.close();
    };
  }, [idsParam, enabled, dismissError]);

  return state;
}
