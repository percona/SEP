import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../client';
import { ApiError } from '../errors';
import type { PluginSchema } from '../types/plugin-schema';

/**
 * Fetches a plugin's schema from the backend.
 *
 * Accepts an optional `mockSchema` fallback for development when the
 * backend doesn't yet serve schemas. When the real API is available,
 * it takes precedence over the mock.
 */
export function usePluginSchema(pluginName: string, mockSchema?: PluginSchema) {
  return useQuery<PluginSchema>({
    queryKey: ['plugins', pluginName, 'schema'],
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<PluginSchema>(`/plugins/${pluginName}/schema`);
        return data;
      } catch (error) {
        // Fall back to mock schema on 404 (not yet served) or network error
        if (mockSchema && error instanceof ApiError) {
          if (error.status === 404 || error.kind === 'network') {
            return mockSchema;
          }
        }
        throw error;
      }
    },
    ...(mockSchema && { placeholderData: mockSchema }),
    staleTime: 5 * 60 * 1000, // schemas rarely change
  });
}
