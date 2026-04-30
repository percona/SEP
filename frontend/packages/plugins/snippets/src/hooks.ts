import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type PluginSchema } from '@sep/api';
import type {
  SnippetExecutionHistoryItem,
  SnippetExecutionRequest,
  SnippetExecutionResponse,
  SnippetResponse,
} from './types';

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
 */
export function useSnippetHistory(filename: string | undefined) {
  return useQuery<SnippetExecutionHistoryItem[]>({
    queryKey: ['snippets', filename, 'history'],
    queryFn: async () => {
      const { data } = await apiClient.get<SnippetExecutionHistoryItem[]>(
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
