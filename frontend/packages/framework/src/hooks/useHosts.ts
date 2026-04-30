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
  /** Detail from the `X-Sep-Hosts-Upstream-Error` header when the Tasks API
   * was unreachable. `null` when the upstream call succeeded. */
  upstreamError: string | null;
}

export interface UseHostsOptions {
  enabled?: boolean;
}

const UPSTREAM_ERROR_HEADER = 'x-sep-hosts-upstream-error';

/**
 * Fetch executor hosts merged with inventory display names.
 *
 * Calls the SEP-side proxy `GET /api/sep/hosts/`, which performs the
 * Tasks/Inventory merge server-side. Loading and error states are
 * first-class React Query states. When the Tasks API is unreachable the
 * route degrades to `200 []` and surfaces the upstream detail via the
 * `X-Sep-Hosts-Upstream-Error` response header — this hook exposes that
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
