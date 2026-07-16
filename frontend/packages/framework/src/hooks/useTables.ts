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

import { useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';
import { apiClient } from '@sep/api';

export interface TableOption {
  id: number;
  name: string;
}

export interface UseTablesOptions {
  /** Single-schema fetch (legacy path). */
  schemaId?: number | null | undefined;
  /** Multi-schema fetch; takes precedence over `schemaId` when non-empty. */
  schemaIds?: readonly number[];
  enabled?: boolean;
}

export interface UseTablesResult {
  data: TableOption[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
}

/**
 * Fetch tables for one or more schemas via the SEP inventory gateway
 * (`GET /sep/schemas/{id}/tables` → `[{id, name}]`).
 *
 * Disabled when no schema ids are provided.
 */
export function useTables(options: UseTablesOptions): UseTablesResult {
  const { schemaId, schemaIds, enabled = true } = options;
  const ids = useMemo(() => {
    if (schemaIds && schemaIds.length > 0) {
      return [...new Set(schemaIds)];
    }
    if (schemaId !== null && schemaId !== undefined) {
      return [schemaId];
    }
    return [];
  }, [schemaId, schemaIds]);

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['inventory', 'tables', id],
      enabled: enabled && ids.length > 0,
      staleTime: 60_000,
      queryFn: async () => {
        const { data } = await apiClient.get<TableOption[]>(`/sep/schemas/${id}/tables`);
        return { schemaId: id, tables: data };
      },
    })),
  });

  const isLoading = queries.some((query) => query.isLoading);
  const isError = queries.some((query) => query.isError);
  const error = queries.find((query) => query.error)?.error ?? null;

  const data = useMemo(() => {
    if (ids.length === 0) {
      return [];
    }
    const qualify = ids.length > 1;
    const merged: TableOption[] = [];
    for (const query of queries) {
      if (!query.data) {
        continue;
      }
      const { schemaId: currentSchemaId, tables } = query.data;
      for (const table of tables) {
        merged.push({
          ...table,
          name: qualify ? `${table.name} (schema ${currentSchemaId})` : table.name,
        });
      }
    }
    return merged;
  }, [ids.length, queries]);

  return { data, isLoading, isError, error };
}
