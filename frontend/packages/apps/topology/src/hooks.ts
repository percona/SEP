/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { useMemo } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { apiClient } from '@sep/api';
import type { TopologyCollectResponse, TopologyResultResponse } from './types';

const TOPOLOGY_BASE = '/apps/topology';

export const TOPOLOGY_RESULT_QUERY_KEY = 'topology-result';

export interface CollectArgs {
  shards?: number;
  executor_host?: string;
  connect_timeout?: number;
  read_timeout?: number;
}

/**
 * Trigger a fresh topology collection. Returns the dispatched task history
 * ids; the caller wires those into `useTopologyResult` for polling (the new
 * ids form a fresh query key, so no manual cache invalidation is needed).
 */
export function useCollectTopology() {
  return useMutation<TopologyCollectResponse, Error, CollectArgs | undefined>({
    mutationFn: async (args) => {
      const { data } = await apiClient.post<TopologyCollectResponse>(
        `${TOPOLOGY_BASE}/collect`,
        args ?? {},
      );
      return data;
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
      if (query.state.status === 'error') {
        return false;
      }
      const data = query.state.data;
      if (!data) {
        return 2000;
      }
      return data.status === 'running' ? 2000 : false;
    },
    refetchOnWindowFocus: false,
  });
}
