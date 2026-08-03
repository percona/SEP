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

import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiClient } from '@sep/api';

const INVENTORY_BASE = '/apps/inventory';

/**
 * Root query key for every inventory entity list (nodes plus the nested
 * services/schemas/tables lists). Mirrors ``entityQueriesRootKey('inventory')``
 * from the shared app task hooks; that helper is not exported, so the literal
 * is duplicated here. Invalidating this prefix cascades to all nested
 * ``['plugins', 'inventory', 'entity', <name>]`` lists by React Query's partial
 * key matching.
 */
const INVENTORY_ENTITY_ROOT_KEY = ['plugins', 'inventory', 'entity'] as const;

export interface Syncer {
  name: string;
  display_name: string;
}

export interface SyncStatus {
  is_running: boolean;
}

/**
 * Result of a per-service database connectivity probe.
 *
 * A probe that ran but could not connect still returns HTTP 200 — `success` is
 * false and `error` carries the upstream reason.
 */
export interface ConnectivityCheckResult {
  success: boolean;
  error?: string | null;
  task_history_id: number;
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
 * app gateway. The upstream returns HTTP 404 when nothing has been
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

/**
 * Re-fetch the inventory entity lists when a sync finishes.
 *
 * The sync runs server-side; the client only learns it completed by polling
 * ``/sync/status/`` (see {@link useSyncStatus}). This hook watches that status
 * and, on the ``is_running`` true → false edge, invalidates the inventory
 * entity root key so React Query re-fetches whatever list is on screen with the
 * freshly synced data.
 *
 * Edge-detection only:
 * - It fires exactly once per running → idle transition, not on every poll
 *   while a sync is still running.
 * - It never fires on initial mount when no sync has run (``undefined`` while
 *   the status is loading, and an initial ``false`` both leave the ref unset).
 *
 * @param isRunning current ``is_running`` value, or ``undefined`` while loading.
 */
export function useRefreshEntitiesOnSyncComplete(isRunning: boolean | undefined) {
  const queryClient = useQueryClient();
  const wasRunning = useRef(false);

  useEffect(() => {
    // Status not loaded yet — leave the previous value untouched so the first
    // real value cannot be mistaken for a transition.
    if (isRunning === undefined) {
      return;
    }
    const transitionedToIdle = wasRunning.current && !isRunning;
    wasRunning.current = isRunning;
    if (transitionedToIdle) {
      queryClient.invalidateQueries({ queryKey: INVENTORY_ENTITY_ROOT_KEY });
    }
  }, [isRunning, queryClient]);
}

/**
 * Probe database connectivity for one service from its executor host.
 *
 * Deliberately invalidates nothing on settle: the probe reads through to the
 * database and changes no server state, so a refetch would be pointless work.
 *
 * @param serviceId inventory primary key of the service to probe.
 */
export function useCheckServiceConnectivity(serviceId: string | number) {
  return useMutation<ConnectivityCheckResult, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<ConnectivityCheckResult>(
        `${INVENTORY_BASE}/services/${serviceId}/check-connectivity/`,
        {},
      );
      return data;
    },
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
    onSuccess: () => {
      // The sync has now started server-side: mark it running so the button
      // stays disabled in the gap between the POST resolving (``isPending``
      // drops) and the next status poll confirming, preventing a duplicate
      // POST. Writing this only on success — not optimistically in onMutate —
      // keeps a *failed* start from later reading as a genuine is_running
      // true→false completion edge to useRefreshEntitiesOnSyncComplete. The
      // button is already disabled while the POST is in flight via isPending.
      queryClient.setQueryData<SyncStatus>(['inventory', 'sync-status'], (prev) =>
        prev ? { ...prev, is_running: true } : { is_running: true },
      );
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory', 'sync-status'] });
    },
  });
}
