import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient } from '@sep/api';

export interface SchemaOption {
  id: number;
  name: string;
}

export interface UseSchemasOptions {
  serviceId: number | null | undefined;
  enabled?: boolean;
}

/**
 * Fetch schemas for a service via the SEP inventory gateway
 * (`GET /inventory-api/services/{id}/schemas` → `[{id, name}]`).
 *
 * Disabled when `serviceId` is nullish.
 */
export function useSchemas(options: UseSchemasOptions): UseQueryResult<SchemaOption[], Error> {
  const { serviceId, enabled = true } = options;
  return useQuery<SchemaOption[], Error>({
    queryKey: ['inventory', 'schemas', serviceId ?? null],
    enabled: enabled && serviceId !== null && serviceId !== undefined,
    staleTime: 60_000,
    queryFn: async () => {
      const { data } = await apiClient.get<SchemaOption[]>(
        `/inventory-api/services/${serviceId}/schemas`,
      );
      return data;
    },
  });
}
