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

/**
 * Predicate used by the mock-fallback gate: returns ``true`` only when the
 * failure looks like the backend is unreachable, never for deterministic 4xx
 * responses. Exported for tests; not part of the public hook surface.
 *
 * 502 is intentionally treated as "backend unavailable" here even though
 * ``sepRetry`` short-circuits on it — the two predicates serve different
 * goals: ``sepRetry`` wants to stop hammering a known-bad gateway, while this
 * gate decides whether to substitute mock data in dev builds. A 502 from
 * ``/api/sep/*`` means the upstream Tasks-API is unreachable, which is
 * exactly the dev-without-backend scenario the mock fallback targets.
 */
export function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.kind === 'network' || (error.kind === 'http' && (error.status ?? 0) >= 500);
  }
  return false;
}

export type PaginatedAppList<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
};

export type AppListPagination = {
  total: number;
  offset: number;
  limit: number;
};

export type AppListResult<T> = {
  items: T[];
  /** ``null`` when the backend returned a bare array (``NO_PAGINATION``). */
  pagination: AppListPagination | null;
};

function isPaginatedAppListEnvelope<T>(data: unknown): data is PaginatedAppList<T> {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return false;
  }
  const candidate = data as PaginatedAppList<T>;
  return (
    Array.isArray(candidate.items) &&
    typeof candidate.total === 'number' &&
    typeof candidate.offset === 'number' &&
    typeof candidate.limit === 'number'
  );
}

/**
 * Normalize a plugin list response to items plus optional pagination metadata.
 *
 * Bare arrays (``NO_PAGINATION``) yield ``pagination: null``; full
 * ``{ items, total, offset, limit }`` envelopes preserve all four fields.
 * Partial ``{ items }`` envelopes (legacy migration shape) unwrap items only.
 */
export function normalizeAppListResponse<T>(
  data: T[] | PaginatedAppList<T> | { items: T[] | null } | null | undefined,
): AppListResult<T> {
  if (Array.isArray(data)) {
    return { items: data, pagination: null };
  }
  if (isPaginatedAppListEnvelope<T>(data)) {
    return {
      items: data.items,
      pagination: {
        total: data.total,
        offset: data.offset,
        limit: data.limit,
      },
    };
  }
  if (data && typeof data === 'object' && 'items' in data) {
    const items = (data as { items: T[] | null }).items;
    return { items: items ?? [], pagination: null };
  }
  return { items: [], pagination: null };
}

/** Accept legacy flat lists or paginated ``{ items, total, offset, limit }`` envelopes. */
export function unwrapAppListResponse<T>(data: T[] | PaginatedAppList<T>): T[] {
  return normalizeAppListResponse(data).items;
}

export const DEFAULT_APP_LIST_OFFSET = 0;
export const DEFAULT_APP_LIST_LIMIT = 50;
export const MAX_APP_LIST_LIMIT = 200;

const MAX_FETCH_ALL_PAGES = 50;

export type AppListQueryOptions = {
  enabled?: boolean;
  offset?: number;
  limit?: number;
  /** When true, fetches every page and returns the full item set (for schedule joins). */
  fetchAllPages?: boolean;
};

function mockItemsToResult<T>(mockItems: T[]): AppListResult<T> {
  return { items: mockItems, pagination: null };
}

function tasksQueryKey(
  pluginName: string,
  options: Pick<AppListQueryOptions, 'offset' | 'limit' | 'fetchAllPages'>,
) {
  return [
    'plugins',
    pluginName,
    'tasks',
    {
      offset: options.offset ?? DEFAULT_APP_LIST_OFFSET,
      limit: options.limit ?? DEFAULT_APP_LIST_LIMIT,
      fetchAllPages: options.fetchAllPages ?? false,
    },
  ] as const;
}

/**
 * Plugin list endpoint shape during the multi-plugin migration:
 * - Legacy plugins return `T[]` directly.
 * - Migrated plugins (e.g. mysql_backups) return `PaginatedResponse<T>`.
 */
type AppListResponse<T> = T[] | PaginatedAppList<T> | { items: T[] | null };

/** @deprecated alias kept for unwrapTasks callers in tests */
type AppTasksResponse<T> = AppListResponse<T>;

export function unwrapTasks<T>(data: AppTasksResponse<T> | null | undefined): T[] {
  return normalizeAppListResponse(data).items;
}

async function fetchAllAppListPages<T extends Record<string, unknown>>(
  path: string,
): Promise<AppListResult<T>> {
  const out: T[] = [];
  let offset = 0;
  // Stay at the default page size: some plugins cap ``limit`` at 50
  // (``DEFAULT_PAGINATION_LIMIT``), so ``MAX_APP_LIST_LIMIT`` (200) 422s there.
  const limit = DEFAULT_APP_LIST_LIMIT;

  for (let iter = 0; iter < MAX_FETCH_ALL_PAGES; iter++) {
    const { data } = await apiClient.get<AppListResponse<T>>(path, {
      params: { offset, limit },
    });
    const page = normalizeAppListResponse(data);

    if (page.pagination === null) {
      return { items: page.items, pagination: null };
    }

    out.push(...page.items);
    offset += page.items.length;
    if (offset >= page.pagination.total || page.items.length === 0) {
      return { items: out, pagination: null };
    }
  }

  return { items: out, pagination: null };
}

async function fetchAppList<T extends Record<string, unknown>>(
  path: string,
  options: Pick<AppListQueryOptions, 'offset' | 'limit' | 'fetchAllPages'> = {},
): Promise<AppListResult<T>> {
  if (options.fetchAllPages) {
    return fetchAllAppListPages<T>(path);
  }
  const offset = options.offset ?? DEFAULT_APP_LIST_OFFSET;
  const limit = options.limit ?? DEFAULT_APP_LIST_LIMIT;
  const { data } = await apiClient.get<AppListResponse<T>>(path, {
    params: { offset, limit },
  });
  return normalizeAppListResponse(data);
}

/** Fetch plugin task list rows, optionally across all pages. */
export async function fetchAppTasksList<T extends Record<string, unknown>>(
  pluginName: string,
  options: Pick<AppListQueryOptions, 'offset' | 'limit' | 'fetchAllPages'> = {},
): Promise<AppListResult<T>> {
  return fetchAppList<T>(`/apps/${pluginName}/`, options);
}

/** Fetch rows for one entity of a multi-entity plugin, optionally across all pages. */
export async function fetchAppEntityList<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  options: Pick<AppListQueryOptions, 'offset' | 'limit' | 'fetchAllPages'> = {},
): Promise<AppListResult<T>> {
  return fetchAppList<T>(`/apps/${pluginName}/${entityName}/`, options);
}

export function useAppTasks<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
  options?: AppListQueryOptions,
) {
  const offset = options?.offset ?? DEFAULT_APP_LIST_OFFSET;
  const limit = options?.limit ?? DEFAULT_APP_LIST_LIMIT;
  const fetchAllPages = options?.fetchAllPages ?? false;

  return useQuery<AppListResult<T>>({
    queryKey: tasksQueryKey(pluginName, { offset, limit, fetchAllPages }),
    enabled: options?.enabled !== false,
    queryFn: async () => {
      try {
        return await fetchAppTasksList<T>(pluginName, { offset, limit, fetchAllPages });
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockTasks && isBackendUnavailable(error)) {
          return mockItemsToResult(mockTasks);
        }
        throw error;
      }
    },
    ...(MOCK_FALLBACKS_ENABLED && mockTasks && { placeholderData: mockItemsToResult(mockTasks) }),
  });
}

export function useAppTask<T extends Record<string, unknown>>(
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
        const { data } = await apiClient.get<T>(
          `/apps/${pluginName}/${encodeURIComponent(taskId!)}`,
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

export function useCreateAppTask<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, Record<string, unknown>>({
    mutationFn: async (values) => {
      try {
        const { data } = await apiClient.post<T>(`/apps/${pluginName}/`, values);
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

export function useUpdateAppTask<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, { taskId: string; values: Record<string, unknown> }>({
    mutationFn: async ({ taskId, values }) => {
      try {
        const { data } = await apiClient.put<T>(
          `/apps/${pluginName}/${encodeURIComponent(taskId)}`,
          values,
        );
        return data;
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockTasks && isBackendUnavailable(error)) {
          return { ...values, name: taskId } as unknown as T;
        }
        throw error;
      }
    },
    onSuccess: (_data, { taskId }) => {
      queryClient.invalidateQueries({ queryKey: ['plugins', pluginName, 'tasks'] });
      queryClient.invalidateQueries({ queryKey: ['plugins', pluginName, 'tasks', taskId] });
    },
  });
}

function entityQueriesPrefix(pluginName: string, entityName: string) {
  return ['plugins', pluginName, 'entity', entityName] as const;
}

function entityListQueryKey(
  pluginName: string,
  entityName: string,
  options: Pick<AppListQueryOptions, 'offset' | 'limit' | 'fetchAllPages'>,
) {
  return [
    ...entityQueriesPrefix(pluginName, entityName),
    {
      offset: options.offset ?? DEFAULT_APP_LIST_OFFSET,
      limit: options.limit ?? DEFAULT_APP_LIST_LIMIT,
      fetchAllPages: options.fetchAllPages ?? false,
    },
  ] as const;
}

function entityQueriesRootKey(pluginName: string) {
  return ['plugins', pluginName, 'entity'] as const;
}

/**
 * Build a per-item URL path for a multi-entity plugin endpoint.
 *
 * ``id`` segments are always URL-encoded so callers cannot smuggle path
 * traversal (``"../foo"``) or sub-paths (``"a/b"``) into the request via a
 * misbehaving backend or attacker-controlled JSON.
 */
export function buildEntityItemPath(pluginName: string, entityName: string, id: string): string {
  return `/apps/${pluginName}/${entityName}/${encodeURIComponent(id)}`;
}

/** List rows for one entity of a multi-entity plugin (GET ``/apps/{name}/{entity}/``). */
export function useAppEntityList<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  mockItems?: T[],
  options?: AppListQueryOptions,
) {
  const offset = options?.offset ?? DEFAULT_APP_LIST_OFFSET;
  const limit = options?.limit ?? DEFAULT_APP_LIST_LIMIT;
  const fetchAllPages = options?.fetchAllPages ?? false;

  return useQuery<AppListResult<T>>({
    queryKey: entityListQueryKey(pluginName, entityName, { offset, limit, fetchAllPages }),
    enabled: options?.enabled !== false,
    queryFn: async () => {
      try {
        return await fetchAppEntityList<T>(pluginName, entityName, {
          offset,
          limit,
          fetchAllPages,
        });
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockItems && isBackendUnavailable(error)) {
          return mockItemsToResult(mockItems);
        }
        throw error;
      }
    },
    ...(MOCK_FALLBACKS_ENABLED && mockItems && { placeholderData: mockItemsToResult(mockItems) }),
  });
}

export function useAppEntityDetail<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  itemId: string | undefined,
  mockItems?: T[],
  options?: { enabled?: boolean },
) {
  return useQuery<T | undefined>({
    queryKey: [...entityQueriesPrefix(pluginName, entityName), itemId],
    enabled: options?.enabled !== false && !!itemId,
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<T>(
          buildEntityItemPath(pluginName, entityName, itemId!),
        );
        return data;
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockItems && isBackendUnavailable(error)) {
          return mockItems.find((t) => String(t.id) === itemId);
        }
        throw error;
      }
    },
  });
}

export function useCreateAppEntity<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  mockItems?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, Record<string, unknown>>({
    mutationFn: async (values) => {
      try {
        const { data } = await apiClient.post<T>(`/apps/${pluginName}/${entityName}/`, values);
        return data;
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockItems && isBackendUnavailable(error)) {
          return values as T;
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: entityQueriesRootKey(pluginName) });
    },
  });
}

export function useUpdateAppEntity<T extends Record<string, unknown>>(
  pluginName: string,
  entityName: string,
  mockItems?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<T, Error, { id: string; values: Record<string, unknown> }>({
    mutationFn: async ({ id, values }) => {
      try {
        const { data } = await apiClient.put<T>(
          buildEntityItemPath(pluginName, entityName, id),
          values,
        );
        return data;
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockItems && isBackendUnavailable(error)) {
          return { ...values, id } as unknown as T;
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: entityQueriesRootKey(pluginName) });
    },
  });
}

export function useDeleteAppEntity(pluginName: string, entityName: string, mockItems?: unknown[]) {
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (id) => {
      try {
        await apiClient.delete(buildEntityItemPath(pluginName, entityName, id));
      } catch (error) {
        if (MOCK_FALLBACKS_ENABLED && mockItems && isBackendUnavailable(error)) {
          return;
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: entityQueriesRootKey(pluginName) });
    },
  });
}

export function useDeleteAppTask<T extends Record<string, unknown>>(
  pluginName: string,
  mockTasks?: T[],
) {
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (taskId) => {
      try {
        await apiClient.delete(`/apps/${pluginName}/${encodeURIComponent(taskId)}`);
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
