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

// Mock-fallback gate. Active in dev builds (`pnpm dev`) and in production
// builds explicitly opted-in via `VITE_MOCK_API=true` (e.g. the Playwright
// preview target). Vite statically replaces both expressions at build time,
// so the fallback branches are dead-code-eliminated in real production.
const MOCK_FALLBACKS_ENABLED = import.meta.env.DEV || import.meta.env.VITE_MOCK_API === 'true';

function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.kind === 'network' || (error.kind === 'http' && (error.status ?? 0) >= 500);
  }
  return false;
}

/**
 * Generic CRUD hooks for plugin tasks.
 *
 * The real API is always attempted first. When the backend is unavailable
 * (network error or 5xx), mock data is used as a fallback only when the
 * mock-fallback gate is on — that is, in dev builds, and in production
 * builds explicitly opted in via `VITE_MOCK_API=true` (the Playwright
 * preview target). Real production bundles never use the fallback.
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
        if (MOCK_FALLBACKS_ENABLED && mockTasks && isBackendUnavailable(error)) {
          return mockTasks;
        }
        throw error;
      }
    },
    ...(MOCK_FALLBACKS_ENABLED && mockTasks && { placeholderData: mockTasks }),
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
        const { data } = await apiClient.get<T>(
          `/plugins/${pluginName}/${encodeURIComponent(taskId!)}`,
        );
        return data;
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockTasks && isBackendUnavailable(error)) {
          // Per-plugin detail/delete routes look up by `task_name`; mocks
          // resolve by the same key so dev fallback matches prod semantics.
          return mockTasks.find((t) => String(t.name ?? t.id) === taskId);
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
        if (MOCK_FALLBACKS_ENABLED && mockTasks && isBackendUnavailable(error)) {
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

export function useDeletePluginTask<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (taskId) => {
      try {
        await apiClient.delete(`/plugins/${pluginName}/${encodeURIComponent(taskId)}`);
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockTasks && isBackendUnavailable(error)) {
          // Mock mode: pretend the delete succeeded so the UI flow can be
          // exercised offline, matching the create/list/detail hooks.
          return;
        }
        throw error;
      }
    },
    onSuccess: (_data, taskId) => {
      queryClient.invalidateQueries({ queryKey: ['plugins', pluginName, 'tasks'] });
      queryClient.removeQueries({ queryKey: ['plugins', pluginName, 'tasks', taskId] });
    },
  });
}
