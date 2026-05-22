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
import { ApiError, sepApi, throwOnApiError } from '@sep/api';

/**
 * Consumer-side view of the task-stats payload.
 *
 * The SEP proxy at ``app/sep/api/routes/task_stats.py`` returns the raw
 * upstream payload (``dict[str, Any]``) and ``{}`` on upstream failure, so
 * every field is optional. Components guard on ``total`` to detect the
 * empty/degraded state.
 */
export interface TaskStatsView {
  engine?: string;
  total?: number;
  status?: { pass?: number; fail?: number };
  duration?: {
    average_seconds?: number | null;
    last_seconds?: number | null;
    total_seconds?: number | null;
  };
  last_finished_at?: string | null;
}

/**
 * Query the aggregated execution statistics for a task by name.
 *
 * The task identifier is the task's ``name`` (string), not the database id.
 * The hook is a no-op when ``taskName`` is missing or whitespace-only.
 */
export function useTaskStats(taskName: string | undefined, enabled = true) {
  const trimmed = taskName?.trim();
  return useQuery<TaskStatsView>({
    queryKey: ['task-stats', trimmed],
    enabled: enabled && Boolean(trimmed),
    queryFn: async () => {
      const data = await throwOnApiError(
        sepApi.GET('/api/sep/task-stats/{task_name}', {
          params: { path: { task_name: trimmed as string } },
        }),
      );
      return data as unknown as TaskStatsView;
    },
    refetchOnWindowFocus: false,
    retry: (count, err) => {
      const status = err instanceof ApiError ? err.status : undefined;
      if (status === 401 || status === 403 || status === 404) {
        return false;
      }
      return count < 2;
    },
    staleTime: 30_000,
  });
}
