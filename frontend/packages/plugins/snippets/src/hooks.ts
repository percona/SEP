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

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type PluginSchema } from '@sep/api';
import type { PaginatedTaskHistory } from '@sep/framework';
import type { SnippetExecutionRequest, SnippetExecutionResponse, SnippetResponse } from './types';

const SNIPPETS_BASE = '/plugins/snippets';

/**
 * Fetch the list of snippet entities discovered by the backend.
 */
export function useSnippets() {
  return useQuery<SnippetResponse[]>({
    queryKey: ['snippets', 'list'],
    queryFn: async () => {
      const { data } = await apiClient.get<SnippetResponse[]>(`${SNIPPETS_BASE}/`);
      return data;
    },
  });
}

/**
 * Fetch the per-snippet form schema, including the script preview field.
 */
export function useSnippetSchema(filename: string | undefined) {
  return useQuery<PluginSchema>({
    queryKey: ['snippets', filename, 'schema'],
    queryFn: async () => {
      const { data } = await apiClient.get<PluginSchema>(
        `${SNIPPETS_BASE}/${encodeURIComponent(filename ?? '')}/schema`,
      );
      return data;
    },
    enabled: Boolean(filename),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Fetch the execution history for a single snippet.
 *
 * Returns the upstream paginated tasks-history payload so the React detail
 * page can pass the result straight into the shared ``TaskHistoryTable``.
 */
export function useSnippetHistory(filename: string | undefined) {
  return useQuery<PaginatedTaskHistory>({
    queryKey: ['snippets', filename, 'history'],
    queryFn: async () => {
      const { data } = await apiClient.get<PaginatedTaskHistory>(
        `${SNIPPETS_BASE}/${encodeURIComponent(filename ?? '')}/history`,
      );
      return data;
    },
    enabled: Boolean(filename),
  });
}

/**
 * Mutation: download the raw snippet file (full body + YAML frontmatter).
 *
 * Routes through ``apiClient`` so the Bearer interceptor attaches the
 * in-memory access token, then turns the Blob response into a save
 * dialog via a temporary anchor click (mirrors ``useLogDownload``).
 */
export function useSnippetDownload(filename: string | undefined) {
  return useMutation<Blob, Error, void>({
    mutationFn: async () => {
      if (!filename) {
        throw new Error('Snippet filename is required for download.');
      }
      const { data } = await apiClient.get<Blob>(
        `${SNIPPETS_BASE}/${encodeURIComponent(filename)}/download`,
        { responseType: 'blob' },
      );
      const url = URL.createObjectURL(data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      return data;
    },
  });
}

/**
 * Mutation: execute a snippet against the tasks API.
 *
 * On success, the per-snippet history list query is invalidated so the
 * detail page refetches and the new run row appears immediately.
 */
export function useSnippetExecution(filename: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation<SnippetExecutionResponse, Error, SnippetExecutionRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<SnippetExecutionResponse>(
        `${SNIPPETS_BASE}/${encodeURIComponent(filename ?? '')}/execute`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      if (filename) {
        queryClient.invalidateQueries({
          queryKey: ['snippets', filename, 'history'],
        });
      }
    },
  });
}
