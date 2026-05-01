/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

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
