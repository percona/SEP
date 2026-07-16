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
import { apiClient, unwrapAppListResponse, useAppSchema, type PaginatedAppList } from '@sep/api';
import { RUNNING_STATUSES } from '@sep/framework';
import {
  TASKS_APP_NAME,
  TASKS_APPS_API_BASE,
  type TaskDetailBundle,
  type TaskListRow,
} from './types';

/** Fetch the read-only Task Manager app schema. */
export function useTasksAppSchema() {
  return useAppSchema(TASKS_APP_NAME);
}

/** Fetch task definition rows for the list view. */
export function useTasksList(options?: { enabled?: boolean }) {
  return useQuery<TaskListRow[]>({
    queryKey: ['tasks', 'list'],
    enabled: options?.enabled !== false,
    queryFn: async () => {
      const { data } = await apiClient.get<TaskListRow[] | PaginatedAppList<TaskListRow>>(
        `${TASKS_APPS_API_BASE}/`,
      );
      return unwrapAppListResponse(data);
    },
  });
}

const TASK_DETAIL_POLL_MS = 5000;

/** Fetch the read-only task detail bundle for a single task definition. */
export function useTaskDetail(taskName: string | undefined) {
  return useQuery<TaskDetailBundle>({
    queryKey: ['tasks', 'detail', taskName],
    enabled: Boolean(taskName),
    queryFn: async () => {
      const { data } = await apiClient.get<TaskDetailBundle>(
        `${TASKS_APPS_API_BASE}/${encodeURIComponent(taskName!)}`,
      );
      return data;
    },
    refetchInterval: (query) => {
      const historyItems = query.state.data?.execution_history.items ?? [];
      return historyItems.some((item) => RUNNING_STATUSES.has(item.status))
        ? TASK_DETAIL_POLL_MS
        : false;
    },
  });
}
