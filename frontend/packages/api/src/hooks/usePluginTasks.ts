import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AxiosError } from 'axios';
import { apiClient } from '../client';

// Only allow mock fallback in development builds.
// Vite (and most bundlers) statically replace process.env.NODE_ENV at build time,
// so this entire code path is dead-code-eliminated in production.
declare const process: { env: { NODE_ENV?: string } };
const IS_DEV = process.env.NODE_ENV !== 'production';

function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof AxiosError) {
    return !error.response || error.response.status >= 500;
  }
  return false;
}

/**
 * Generic CRUD hooks for plugin tasks.
 *
 * In development, the real API is attempted first. If the backend is
 * unavailable (network error or 5xx), mock data is used as a fallback.
 * In production builds, mock data is never used.
 */

export function usePluginTasks<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  return useQuery<T[]>({
    queryKey: ['plugins', pluginName, 'tasks'],
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<T[]>(`/plugins/${pluginName}/`);
        return data;
      } catch (error) {
        if (IS_DEV && mockTasks && isBackendUnavailable(error)) {
          return mockTasks;
        }
        throw error;
      }
    },
    ...(IS_DEV && mockTasks && { placeholderData: mockTasks }),
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
      try {
        const { data } = await apiClient.get<T>(`/plugins/${pluginName}/${taskId}`);
        return data;
      } catch (error) {
        if (IS_DEV && mockTasks && isBackendUnavailable(error)) {
          return mockTasks.find((t) => String(t.id) === taskId);
        }
        throw error;
      }
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
      try {
        const { data } = await apiClient.post<T>(`/plugins/${pluginName}/`, values);
        return data;
      } catch (error) {
        if (IS_DEV && mockTasks && isBackendUnavailable(error)) {
          return values as T;
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plugins', pluginName, 'tasks'] });
    },
  });
}
