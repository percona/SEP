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

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@sep/api';

const INVENTORY_BASE = '/plugins/inventory';

export interface Syncer {
  name: string;
  display_name: string;
}

export interface SyncStatus {
  is_running: boolean;
}

export function useAvailableSyncers() {
  return useQuery<Syncer[]>({
    queryKey: ['inventory', 'available-syncers'],
    queryFn: async () => {
      const { data } = await apiClient.get<Syncer[]>(`${INVENTORY_BASE}/available-syncers/`);
      return data;
    },
    staleTime: 60_000,
  });
}

export function useSyncStatus(enabled = true) {
  return useQuery<SyncStatus>({
    queryKey: ['inventory', 'sync-status'],
    queryFn: async () => {
      const { data } = await apiClient.get<SyncStatus>(`${INVENTORY_BASE}/sync/status/`);
      return data;
    },
    // Poll fast while a sync is running, slow while idle.
    refetchInterval: (query) => (query.state.data?.is_running ? 3_000 : 30_000),
    enabled,
  });
}

export function useTriggerSync() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, string | undefined>({
    mutationFn: async (syncerName) => {
      const body = syncerName ? { syncer: syncerName } : {};
      const { data } = await apiClient.post(`${INVENTORY_BASE}/sync/`, body);
      return data;
    },
    onMutate: () => {
      // Optimistically mark as running so the button disables immediately,
      // preventing a second POST before the status refetch returns.
      queryClient.setQueryData<SyncStatus>(['inventory', 'sync-status'], (prev) =>
        prev ? { ...prev, is_running: true } : { is_running: true },
      );
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory', 'sync-status'] });
    },
  });
}
