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

import { useMutation, useQuery } from '@tanstack/react-query';
import { apiClient, type PluginSchema } from '@sep/api';
import type {
  AtwCategoryListing,
  SnippetExecutionRequest,
  SnippetExecutionResponse,
} from './types';

const ATW_BASE = '/plugins/atw';

const ATW_STALE_TIME_MS = 5 * 60 * 1000;

export function useAtwCategories() {
  return useQuery<AtwCategoryListing[]>({
    queryKey: ['atw', 'categories'],
    queryFn: async () => {
      const { data } = await apiClient.get<AtwCategoryListing[]>(`${ATW_BASE}/`);
      return data;
    },
    staleTime: ATW_STALE_TIME_MS,
  });
}

export function useSnippetSchema(schemaUrl: string | null) {
  return useQuery<PluginSchema>({
    queryKey: ['atw', 'snippet-schema', schemaUrl],
    queryFn: async () => {
      if (!schemaUrl) {
        throw new Error('Missing snippet schema URL');
      }
      const { data } = await apiClient.get<PluginSchema>(schemaUrl);
      return data;
    },
    enabled: Boolean(schemaUrl),
    staleTime: ATW_STALE_TIME_MS,
  });
}

export function useSnippetExecution(executeUrl: string | null) {
  return useMutation<SnippetExecutionResponse, Error, SnippetExecutionRequest>({
    mutationFn: async (body) => {
      if (!executeUrl) {
        throw new Error('Missing snippet execute URL');
      }
      const { data } = await apiClient.post<SnippetExecutionResponse>(executeUrl, body);
      return data;
    },
  });
}
