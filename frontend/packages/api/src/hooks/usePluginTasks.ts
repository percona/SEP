import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../client';

/**
 * Generic CRUD hooks for plugin tasks.
 *
 * Accepts mockTasks for development. When the backend serves real data
 * at /api/plugins/{name}/, the mock is bypassed.
 */

export function usePluginTasks<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  return useQuery<T[]>({
    queryKey: ['plugins', pluginName, 'tasks'],
    queryFn: async () => {
      // TODO: switch to real API
      if (mockTasks) {
        await new Promise((r) => setTimeout(r, 300));
        return mockTasks;
      }
      const { data } = await apiClient.get<T[]>(`/plugins/${pluginName}/`);
      return data;
    },
    ...(mockTasks && { placeholderData: mockTasks }),
  });
}

export function usePluginTask<T extends Record<string, unknown>>(
  pluginName: string,
  taskId: string | undefined,
  mockTasks?: T[],
) {
  return useQuery<T | undefined>({
    queryKey: ['plugins', pluginName, 'tasks', taskId],
    enabled: !!taskId,
    queryFn: async () => {
      // TODO: switch to real API
      if (mockTasks) {
        await new Promise((r) => setTimeout(r, 200));
        return mockTasks.find((t) => String(t.id) === taskId);
      }
      const { data } = await apiClient.get<T>(`/plugins/${pluginName}/${taskId}`);
      return data;
    },
  });
}

export function useCreatePluginTask<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, Record<string, unknown>>({
    mutationFn: async (values) => {
      if (mockTasks) {
        await new Promise((r) => setTimeout(r, 500));
        return values as T;
      }
      const { data } = await apiClient.post<T>(`/plugins/${pluginName}/`, values);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugins', pluginName, 'tasks'] });
    },
  });
}
