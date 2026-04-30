import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient } from '@sep/api';

export interface TableOption {
  id: number;
  name: string;
}

export interface UseTablesOptions {
  schemaId: number | null | undefined;
  enabled?: boolean;
}

/**
 * Fetch tables for a schema via the SEP inventory gateway
 * (`GET /inventory-api/schemas/{id}/tables` → `[{id, name}]`).
 *
 * Disabled when `schemaId` is nullish.
 */
export function useTables(options: UseTablesOptions): UseQueryResult<TableOption[], Error> {
  const { schemaId, enabled = true } = options;
  return useQuery<TableOption[], Error>({
    queryKey: ['inventory', 'tables', schemaId ?? null],
    enabled: enabled && schemaId !== null && schemaId !== undefined,
    staleTime: 60_000,
    queryFn: async () => {
      const { data } = await apiClient.get<TableOption[]>(
        `/inventory-api/schemas/${schemaId}/tables`,
      );
      return data;
    },
  });
}
