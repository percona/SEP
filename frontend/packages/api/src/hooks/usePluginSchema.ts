import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../client';
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
        if (mockSchema) {
          const status = (error as { response?: { status?: number } }).response?.status;
          const hasNoResponse = !(error as { response?: unknown }).response;
          if (status === 404 || hasNoResponse) {
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
