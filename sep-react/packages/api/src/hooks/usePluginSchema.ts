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
      // TODO: switch to real API once backend serves plugin schemas
      // const { data } = await apiClient.get<PluginSchema>(`/plugins/${pluginName}/schema`);
      // return data;
      if (mockSchema) return mockSchema;
      const { data } = await apiClient.get<PluginSchema>(`/plugins/${pluginName}/schema`);
      return data;
    },
    ...(mockSchema && { placeholderData: mockSchema }),
    staleTime: 5 * 60 * 1000, // schemas rarely change
  });
}
