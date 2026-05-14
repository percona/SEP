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
import { apiClient, type TasksComponents } from '@sep/api';

export type TaskHistoryStatus = TasksComponents['schemas']['TaskHistoryStatusEnum'];
export type TaskHistoryEntry = TasksComponents['schemas']['TaskHistoryResponse'];
export type PaginatedTaskHistory =
  TasksComponents['schemas']['PaginatedResponse_TaskHistoryResponse_'];

export const RUNNING_STATUSES: ReadonlySet<TaskHistoryStatus> = new Set(['running', 'pending']);

export function isRunningStatus(status: TaskHistoryStatus): boolean {
  return RUNNING_STATUSES.has(status);
}

export interface UseTaskHistoryOptions {
  /** Filter by exact status (server-side ?status=). */
  status?: TaskHistoryStatus | null;
  /** Override polling interval (ms). Defaults to 5000. */
  pollingIntervalMs?: number;
  /** Disable polling regardless of running tasks. */
  disablePolling?: boolean;
  /** Optional offset/limit for client-side prefetch (server pagination is deferred). */
  offset?: number;
  limit?: number;
  /** Disable the underlying query (no fetch, no polling). */
  enabled?: boolean;
}

interface ListParams {
  status?: TaskHistoryStatus | null;
  offset?: number;
  limit?: number;
}

function buildParams({ status, offset, limit }: ListParams): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (status) {
    params.status = status;
  }
  if (typeof offset === 'number') {
    params.offset = offset;
  }
  if (typeof limit === 'number') {
    params.limit = limit;
  }
  return params;
}

function refetchIntervalFor(
  data: PaginatedTaskHistory | undefined,
  pollingMs: number,
  disabled: boolean,
): number | false {
  if (disabled) {
    return false;
  }
  if (!data) {
    return false;
  }
  const hasRunning = data.items.some((entry) => isRunningStatus(entry.status));
  return hasRunning ? pollingMs : false;
}

/**
 * List task history across all tasks.
 *
 * Polling activates only when at least one row is in a running state, matching
 * the legacy Jinja2 page reload behaviour. Server cursor pagination is deferred
 * (SEP-923/924/925); callers paginate client-side for now.
 */
export function useTaskHistory(options: UseTaskHistoryOptions = {}) {
  const {
    status,
    pollingIntervalMs = 5000,
    disablePolling = false,
    offset,
    limit,
    enabled = true,
  } = options;
  return useQuery<PaginatedTaskHistory>({
    queryKey: ['task-history', { status: status ?? null, offset, limit }],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<PaginatedTaskHistory>('/tasks/history/', {
        params: buildParams({ status, offset, limit }),
      });
      return data;
    },
    refetchInterval: (query) =>
      refetchIntervalFor(query.state.data, pollingIntervalMs, disablePolling),
  });
}

/**
 * List task history filtered to a specific task by name.
 */
export function useTaskHistoryByName(
  taskName: string | undefined,
  options: UseTaskHistoryOptions = {},
) {
  const {
    status,
    pollingIntervalMs = 5000,
    disablePolling = false,
    offset,
    limit,
    enabled = true,
  } = options;
  return useQuery<PaginatedTaskHistory>({
    queryKey: ['task-history', taskName, { status: status ?? null, offset, limit }],
    enabled: enabled && !!taskName,
    queryFn: async () => {
      const { data } = await apiClient.get<PaginatedTaskHistory>(
        `/tasks/${encodeURIComponent(taskName!)}/history/`,
        { params: buildParams({ status, offset, limit }) },
      );
      return data;
    },
    refetchInterval: (query) =>
      refetchIntervalFor(query.state.data, pollingIntervalMs, disablePolling),
  });
}

/**
 * Stop a running task history execution.
 */
export function useStopTaskHistory() {
  const queryClient = useQueryClient();
  return useMutation<TaskHistoryEntry, Error, number>({
    mutationFn: async (taskHistoryId) => {
      const { data } = await apiClient.post<TaskHistoryEntry>(
        `/tasks/history/${taskHistoryId}/stop/`,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-history'] });
    },
  });
}
