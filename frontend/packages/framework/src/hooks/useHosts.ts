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

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient } from '@sep/api';

export interface HostOption {
  /** Executor node name — the value sent to the dispatch payload as `executor_host`. */
  id: string;
  /** Human-readable label: inventory display name when available, else `id`. */
  name: string;
  /** Network address reported by the executor. */
  address: string;
}

export interface HostsResult {
  hosts: HostOption[];
  /** Detail from the `X-Sep-Upstream-Error` header when the Tasks API
   * was unreachable. `null` when the upstream call succeeded. */
  upstreamError: string | null;
}

export interface UseHostsOptions {
  enabled?: boolean;
}

const UPSTREAM_ERROR_HEADER = 'x-sep-upstream-error';

/**
 * Fetch executor hosts merged with inventory display names.
 *
 * Calls the SEP-side proxy `GET /api/sep/hosts/`, which performs the
 * Tasks/Inventory merge server-side. Loading and error states are
 * first-class React Query states. When the Tasks API is unreachable the
 * route degrades to `200 []` and surfaces the upstream detail via the
 * `X-Sep-Upstream-Error` response header — this hook exposes that
 * detail as `data.upstreamError` so the consumer can raise a notification.
 */
export function useHosts(options: UseHostsOptions = {}): UseQueryResult<HostsResult, Error> {
  const { enabled = true } = options;
  return useQuery<HostsResult, Error>({
    queryKey: ['sep', 'hosts'],
    enabled,
    staleTime: 60_000,
    queryFn: async () => {
      const response = await apiClient.get<HostOption[]>('/sep/hosts/');
      const upstreamError = response.headers[UPSTREAM_ERROR_HEADER] ?? null;
      return { hosts: response.data, upstreamError };
    },
  });
}
