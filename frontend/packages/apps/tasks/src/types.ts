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

import type { TasksComponents } from '@sep/api';

/** App key used for ``/api/apps/{name}/`` routes and schema fetching. */
export const TASKS_APP_NAME = 'tasks';

/** Base path for the tasks app JSON API under the SEP layer. */
export const TASKS_APPS_API_BASE = '/apps/tasks';

/** One task row from ``GET /api/apps/tasks/``. */
export interface TaskListRow {
  name: string;
  backend: string;
  created_at: string | null;
  created_by: string | null;
  last_updated_by: string | null;
}

/** Read-only periodic schedule row from the task detail bundle. */
export interface PeriodicTaskSummaryRow {
  id: number;
  name: string;
  enabled: boolean;
  period: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  total_run_count: number | null;
  chain_task_names: string[];
}

export interface ExecutorHostRow {
  value: string;
  label: string;
}

export type TaskDetailTask = TasksComponents['schemas']['TaskResponse'];
export type TaskExecutionHistory =
  TasksComponents['schemas']['PaginatedResponse_TaskHistoryResponse_'];

/** Payload from ``GET /api/apps/tasks/{task_name}``. */
export interface TaskDetailBundle {
  task: TaskDetailTask;
  execution_history: TaskExecutionHistory;
  periodic_summary: PeriodicTaskSummaryRow[];
  executor_hosts: ExecutorHostRow[];
}
