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
import { apiClient, ApiError, type PluginSchema } from '@sep/api';
import type { PaginatedTaskHistory } from '@sep/framework';
import type {
  BatchApprovalErrorResponse,
  BatchApprovalResponse,
  SnippetApprovalResponse,
  SnippetBatchApproveRequest,
  SnippetExecutionRequest,
  SnippetExecutionResponse,
  SnippetResponse,
} from './types';

const SNIPPETS_BASE = '/plugins/snippets';

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function extractBatchApprovalError(data: unknown): BatchApprovalErrorResponse | null {
  if (!data || typeof data !== 'object') {
    return null;
  }

  const detail = (data as { detail?: unknown }).detail;
  if (!detail || typeof detail !== 'object') {
    return null;
  }

  const candidate = detail as {
    missing_in_db?: unknown;
    missing_on_disk?: unknown;
  };
  if (!isStringArray(candidate.missing_in_db) || !isStringArray(candidate.missing_on_disk)) {
    return null;
  }

  return {
    missing_in_db: candidate.missing_in_db,
    missing_on_disk: candidate.missing_on_disk,
  };
}

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

/**
 * Mutation: approve a single snippet (idempotent PUT).
 *
 * On success, the snippets list query is invalidated so the list view
 * reflects the new approval state immediately.
 */
export function useApproveSnippet(filename: string) {
  const queryClient = useQueryClient();
  return useMutation<SnippetApprovalResponse, Error, void, { previous?: SnippetResponse[] }>({
    mutationFn: async () => {
      const { data } = await apiClient.put<SnippetApprovalResponse>(
        `${SNIPPETS_BASE}/${encodeURIComponent(filename)}/approval`,
      );
      return data;
    },
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['snippets', 'list'] });
      const previous = queryClient.getQueryData<SnippetResponse[]>(['snippets', 'list']);
      if (previous) {
        queryClient.setQueryData<SnippetResponse[]>(
          ['snippets', 'list'],
          previous.map((s) => (s.filename === filename ? { ...s, is_approved: true } : s)),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['snippets', 'list'], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', 'list'] });
    },
  });
}

/**
 * Mutation: remove approval from a single snippet (idempotent DELETE).
 *
 * On success, the snippets list query is invalidated.
 */
export function useRemoveSnippetApproval(filename: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, void, { previous?: SnippetResponse[] }>({
    mutationFn: async () => {
      await apiClient.delete(`${SNIPPETS_BASE}/${encodeURIComponent(filename)}/approval`);
    },
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['snippets', 'list'] });
      const previous = queryClient.getQueryData<SnippetResponse[]>(['snippets', 'list']);
      if (previous) {
        queryClient.setQueryData<SnippetResponse[]>(
          ['snippets', 'list'],
          previous.map((s) => (s.filename === filename ? { ...s, is_approved: false } : s)),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['snippets', 'list'], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', 'list'] });
    },
  });
}

/**
 * Mutation: batch-approve snippets via PATCH /approvals (idempotent).
 *
 * Returns a {@link BatchApprovalResponse} on success (200) or throws a
 * structured error carrying the {@link BatchApprovalErrorResponse} body
 * on hard failures (400) so the UI can render per-category badges.
 */
export function useBatchApproveSnippets() {
  const queryClient = useQueryClient();
  return useMutation<
    BatchApprovalResponse,
    { response?: BatchApprovalErrorResponse },
    SnippetBatchApproveRequest
  >({
    mutationFn: async (body) => {
      try {
        const { data } = await apiClient.patch<BatchApprovalResponse>(
          `${SNIPPETS_BASE}/approvals`,
          body,
        );
        return data;
      } catch (err: unknown) {
        const detail =
          err instanceof ApiError && err.status === 400
            ? extractBatchApprovalError(err.data)
            : null;
        if (detail) {
          throw { response: detail };
        }
        throw err;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', 'list'] });
    },
  });
}
