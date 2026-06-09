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
import { apiClient } from '../client';

/** Minimal per-app entry returned by the public ``GET /api/apps/`` endpoint. */
export interface EnabledApp {
  app_key: string;
  enabled: boolean;
  sidebar: boolean;
  uri_path: string;
}

export const ENABLED_APPS_QUERY_KEY = ['apps'] as const;

/**
 * Fetches the per-app enabled state for the current user's navigation.
 *
 * Powers the shell's sidebar filtering: items tagged with a disabled app's
 * key are hidden. The data is cached for 30s — admins toggle apps
 * infrequently and a brief staleness is acceptable for navigation.
 */
export function useEnabledApps() {
  return useQuery<EnabledApp[]>({
    queryKey: ENABLED_APPS_QUERY_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<EnabledApp[]>('/apps/');
      return data;
    },
    staleTime: 30_000,
  });
}
