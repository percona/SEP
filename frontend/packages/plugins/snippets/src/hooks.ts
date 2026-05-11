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
import { apiClient, ApiError } from '@sep/api';
import { SNIPPETS_PLUGINS_API_BASE, type PaginatedTaskHistory } from '@sep/framework';
import type {
  BatchApprovalErrorResponse,
  BatchApprovalResponse,
  SnippetBatchApproveRequest,
  SnippetResponse,
} from './types';

const SNIPPETS_BASE = SNIPPETS_PLUGINS_API_BASE;

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
 * Fetch the execution history for a single snippet.
 *
 * Returns the upstream paginated tasks-history payload so the React detail
 * page can pass the result straight into the shared ``TaskHistoryTable``.
 */
export function useSnippetHistory(filename: string | undefined) {
  return useQuery<PaginatedTaskHistory>({
    queryKey: ['snippets', filename, 'history'],
    queryFn: async () => {
      if (!filename) {
        throw new Error('Missing snippet filename');
      }
      const { data } = await apiClient.get<PaginatedTaskHistory>(
        `${SNIPPETS_BASE}/${encodeURIComponent(filename)}/history`,
      );
      return data;
    },
    enabled: Boolean(filename),
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
  return useMutation<SnippetResponse, Error, void, { previous?: SnippetResponse[] }>({
    mutationFn: async () => {
      const { data } = await apiClient.put<SnippetResponse>(
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
 * Discriminated error union for {@link useBatchApproveSnippets}.
 *
 * `structured: true` — the backend returned a 400 with a parseable
 * {@link BatchApprovalErrorResponse} payload (missing DB rows / disk files).
 * `structured: false` — any other failure (network error, 5xx, etc.); the
 * raw value is preserved in `raw` for logging.
 */
export type BatchApproveError =
  | (Error & { structured: true; detail: BatchApprovalErrorResponse })
  | (Error & { structured: false; raw: unknown });

/**
 * Mutation: batch-approve snippets via PATCH /approvals (idempotent).
 *
 * Returns a {@link BatchApprovalResponse} on success (200) or throws a
 * {@link BatchApproveError} so callers can narrow on `err.structured`
 * to render per-category badges (400) vs. a generic fallback message.
 */
export function useBatchApproveSnippets() {
  const queryClient = useQueryClient();
  return useMutation<BatchApprovalResponse, BatchApproveError, SnippetBatchApproveRequest>({
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
          const batchError: BatchApproveError = Object.assign(new Error('Batch approval failed'), {
            structured: true as const,
            detail,
          });
          throw batchError;
        }
        const batchError: BatchApproveError = Object.assign(new Error('Batch approval failed'), {
          structured: false as const,
          raw: err,
        });
        throw batchError;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['snippets', 'list'] });
    },
  });
}
