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

import { useQuery } from '@tanstack/react-query';
import { apiClient, type AppSchema } from '@sep/api';

const SNIPPET_APP_SCHEMA_STALE_MS = 5 * 60 * 1000;

/**
 * Load a snippets-app schema from an API path relative to `/api`
 * (e.g. `/apps/snippets/my-script.sh/schema`, including encoded slashes).
 *
 * Shared by the snippets detail page (path derived from filename) and flows
 * like ATW that compose the same URLs client-side.
 */
export function useSnippetAppSchema(apiPath: string | null | undefined) {
  return useQuery<AppSchema>({
    queryKey: ['apps', 'snippets', 'schema', apiPath ?? ''],
    queryFn: async () => {
      if (!apiPath) {
        throw new Error('Missing snippets app schema path');
      }
      const { data } = await apiClient.get<AppSchema>(apiPath);
      return data;
    },
    enabled: Boolean(apiPath),
    staleTime: SNIPPET_APP_SCHEMA_STALE_MS,
  });
}
