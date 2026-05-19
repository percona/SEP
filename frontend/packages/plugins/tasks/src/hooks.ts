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
import { apiClient, usePluginSchema } from '@sep/api';
import { TASKS_PLUGIN_NAME, TASKS_PLUGINS_API_BASE, type TaskListRow } from './types';

/** Fetch the read-only Task Manager plugin schema. */
export function useTasksPluginSchema() {
  return usePluginSchema(TASKS_PLUGIN_NAME);
}

/** Fetch task definition rows for the list view. */
export function useTasksList(options?: { enabled?: boolean }) {
  return useQuery<TaskListRow[]>({
    queryKey: ['tasks', 'list'],
    enabled: options?.enabled !== false,
    queryFn: async () => {
      const { data } = await apiClient.get<TaskListRow[]>(`${TASKS_PLUGINS_API_BASE}/`);
      return data;
    },
  });
}
