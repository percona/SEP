/// <reference path="../vite-env.d.ts" />
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../client';
import { ApiError } from '../errors';

// Only allow mock fallback in development builds. Vite statically replaces
// `import.meta.env.DEV` at build time, so this path is dead-code-eliminated
// in production.
const IS_DEV = import.meta.env.DEV;

function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.kind === 'network' || (error.kind === 'http' && (error.status ?? 0) >= 500);
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
  options?: { enabled?: boolean },
) {
  return useQuery<T[]>({
    queryKey: ['plugins', pluginName, 'tasks'],
    enabled: options?.enabled !== false,
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
  options?: { enabled?: boolean },
) {
  return useQuery<T | undefined>({
    queryKey: ['plugins', pluginName, 'tasks', taskId],
    enabled: options?.enabled !== false && !!taskId,
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

function entityQueryKey(pluginName: string, entityName: string) {
  return ['plugins', pluginName, 'entity', entityName] as const;
}

/** List rows for one entity of a multi-entity plugin (GET ``/plugins/{name}/{entity}/``). */
export function usePluginEntityList<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  mockItems?: T[],
  options?: { enabled?: boolean },
) {
  return useQuery<T[]>({
    queryKey: entityQueryKey(pluginName, entityName),
    enabled: options?.enabled !== false,
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<T[]>(`/plugins/${pluginName}/${entityName}/`);
        return data;
      } catch (error) {
        if (IS_DEV && mockItems && isBackendUnavailable(error)) {
          return mockItems;
        }
        throw error;
      }
    },
    ...(IS_DEV && mockItems && { placeholderData: mockItems }),
  });
}

export function usePluginEntityDetail<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  itemId: string | undefined,
  mockItems?: T[],
  options?: { enabled?: boolean },
) {
  return useQuery<T | undefined>({
    queryKey: [...entityQueryKey(pluginName, entityName), itemId],
    enabled: options?.enabled !== false && !!itemId,
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<T>(`/plugins/${pluginName}/${entityName}/${itemId}`);
        return data;
      } catch (error) {
        if (IS_DEV && mockItems && isBackendUnavailable(error)) {
          return mockItems.find((t) => String(t.id) === itemId);
        }
        throw error;
      }
    },
  });
}

export function useCreatePluginEntity<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  mockItems?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, Record<string, unknown>>({
    mutationFn: async (values) => {
      try {
        const { data } = await apiClient.post<T>(`/plugins/${pluginName}/${entityName}/`, values);
        return data;
      } catch (error) {
        if (IS_DEV && mockItems && isBackendUnavailable(error)) {
          return values as T;
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: entityQueryKey(pluginName, entityName) });
    },
  });
}

export function useUpdatePluginEntity<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  mockItems?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, { id: string; values: Record<string, unknown> }>({
    mutationFn: async ({ id, values }) => {
      try {
        const { data } = await apiClient.put<T>(
          `/plugins/${pluginName}/${entityName}/${id}`,
          values,
        );
        return data;
      } catch (error) {
        if (IS_DEV && mockItems && isBackendUnavailable(error)) {
          return { ...values, id } as unknown as T;
        }
        throw error;
      }
    },
    onSuccess: (_data, { id }) => {
      queryClient.invalidateQueries({ queryKey: entityQueryKey(pluginName, entityName) });
      queryClient.invalidateQueries({
        queryKey: [...entityQueryKey(pluginName, entityName), id],
      });
    },
  });
}

export function useDeletePluginEntity(
  pluginName: string,
  entityName: string,
  mockItems?: unknown[],
) {
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (id) => {
      try {
        await apiClient.delete(`/plugins/${pluginName}/${entityName}/${id}`);
      } catch (error) {
        if (IS_DEV && mockItems && isBackendUnavailable(error)) {
          return;
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: entityQueryKey(pluginName, entityName) });
    },
  });
}
