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
import { ApiError, apiClient } from '@sep/api';

const INVENTORY_BASE = '/plugins/inventory';

export interface Syncer {
  name: string;
  display_name: string;
}

export interface SyncStatus {
  is_running: boolean;
}

/**
 * Host- or service-level system facts collected by the syncer.
 * ``installed_packages`` and ``config`` are arbitrary JSON blobs whose exact
 * shape is owned upstream, so they stay loosely typed and are rendered
 * defensively by the panel.
 */
export interface SystemObservation {
  os_version?: string | null;
  db_engine_version?: string | null;
  installed_packages?: unknown;
  config?: unknown;
  observed_at?: string | null;
  [key: string]: unknown;
}

export type SystemObservationEntity = 'nodes' | 'services';

/**
 * Fetch the system observation for a node or service through the inventory
 * plugin gateway. The upstream returns HTTP 404 when nothing has been
 * collected yet; that is the expected "not collected" signal rather than a
 * failure, so it is normalized to ``null`` (an empty state) instead of an
 * error. All other failures propagate to React Query as usual.
 */
export function useSystemObservation(
  entity: SystemObservationEntity,
  id: string | number | undefined,
  enabled = true,
) {
  return useQuery<SystemObservation | null>({
    queryKey: ['inventory', 'system-observation', entity, id],
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<SystemObservation>(
          `${INVENTORY_BASE}/${entity}/${id}/system-observation`,
        );
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },
    // Inventory PKs are integers and the proxy route is typed ``:int``; only
    // fire for a numeric id so a non-numeric value can never produce a 422
    // that masquerades as a generic error instead of the 404 empty state.
    enabled: enabled && id !== undefined && id !== null && /^\d+$/.test(String(id)),
    staleTime: 60_000,
  });
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
