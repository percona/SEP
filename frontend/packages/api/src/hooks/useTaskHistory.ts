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
import type { components } from '../generated/tasks';
import { apiClient } from '../client';

export type TaskHistoryItem = components['schemas']['TaskHistoryResponse'];

interface PaginatedTaskHistory {
  items: TaskHistoryItem[];
  total: number;
  offset: number;
  limit: number;
}

export function useRecentTaskHistory(limit = 5) {
  return useQuery<PaginatedTaskHistory>({
    queryKey: ['tasks', 'history', { limit }],
    queryFn: async () => {
      const { data } = await apiClient.get<PaginatedTaskHistory>('/tasks/history/', {
        params: { limit },
      });
      return data;
    },
  });
}
