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

export interface UseHostsOptions {
  enabled?: boolean;
}

/**
 * Fetch executor hosts merged with inventory display names.
 *
 * Calls the SEP-side proxy `GET /api/sep/hosts/`, which performs the
 * Tasks/Inventory merge server-side. Loading and error states are
 * first-class React Query states.
 */
export function useHosts(options: UseHostsOptions = {}): UseQueryResult<HostOption[], Error> {
  const { enabled = true } = options;
  return useQuery<HostOption[], Error>({
    queryKey: ['sep', 'hosts'],
    enabled,
    staleTime: 60_000,
    queryFn: async () => {
      const { data } = await apiClient.get<HostOption[]>('/sep/hosts/');
      return data;
    },
  });
}
