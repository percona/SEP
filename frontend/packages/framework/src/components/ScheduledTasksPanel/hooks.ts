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
import {
  apiClient,
  DEFAULT_APP_LIST_LIMIT,
  MAX_FETCH_ALL_PAGES,
  normalizeAppListResponse,
  useAppTasks,
  type TasksComponents,
} from '@sep/api';

export type PeriodicTaskResponse = TasksComponents['schemas']['PeriodicTaskResponse'];
export type PeriodicTaskCreate = TasksComponents['schemas']['PeriodicTaskCreate'];
export type PeriodicTaskUpdate = TasksComponents['schemas']['PeriodicTaskUpdate'];
export type IntervalSchedule = TasksComponents['schemas']['IntervalSchedule'];
export type CrontabSchedule = TasksComponents['schemas']['CrontabSchedule'];
export type PeriodicTaskExecuteRequest = TasksComponents['schemas']['PeriodicTaskExecuteRequest'];

const PERIODIC_LIST_KEY = ['periodic'] as const;
const PERIODIC_LIST_PATH = '/sep/periodic-tasks/';
const POLL_INTERVAL_MS = 30_000;

interface AppTask extends Record<string, unknown> {
  name: string;
}

/**
 * Walk every page of the SEP periodic-task list before client-side filtering.
 *
 * Mirrors ``fetchAllAppListPages`` so a large schedule table cannot hide this
 * plugin's rows past the first page. Bare-array responses (stories/tests)
 * short-circuit after one request; hitting the page cap surfaces a warning
 * rather than silently dropping schedules.
 */
async function fetchAllPeriodicTasks(): Promise<PeriodicTaskResponse[]> {
  const out: PeriodicTaskResponse[] = [];
  let offset = 0;
  let lastTotal: number | null = null;
  const limit = DEFAULT_APP_LIST_LIMIT;

  for (let iter = 0; iter < MAX_FETCH_ALL_PAGES; iter++) {
    const { data } = await apiClient.get(PERIODIC_LIST_PATH, {
      params: { offset, limit },
    });
    const page = normalizeAppListResponse<PeriodicTaskResponse>(data);

    if (page.pagination === null) {
      return page.items;
    }

    lastTotal = page.pagination.total;
    out.push(...page.items);
    offset += page.items.length;
    if (offset >= page.pagination.total || page.items.length === 0) {
      return out;
    }
  }

  // eslint-disable-next-line no-console -- surface silent schedule-list truncation
  console.warn(
    `[api] fetchAllPages truncated ${PERIODIC_LIST_PATH} at ${out.length} of ${lastTotal ?? '?'} items ` +
      `(cap ${MAX_FETCH_ALL_PAGES}×${limit})`,
  );
  return out;
}

/**
 * Fetch all periodic tasks and filter to those whose `task` belongs to the
 * given plugin (resolved via `useAppTasks`). The two queries are kept
 * independent so the periodic list can poll on its own cadence for
 * `last_run_at` / `next_run_at` freshness.
 */
export interface UseScheduledTasksOptions {
  /** Override polling interval (ms). Defaults to 30000. */
  pollingIntervalMs?: number;
  /** Disable polling (stories, tests). */
  disablePolling?: boolean;
}

export function useScheduledTasksForApp(
  pluginName: string,
  options: UseScheduledTasksOptions = {},
) {
  const { pollingIntervalMs = POLL_INTERVAL_MS, disablePolling = false } = options;
  // Forward the escape hatch: `useAppTasks` now polls while a task row is
  // running, so without this a story/test that sets `disablePolling` would
  // still spin up a live task-list refetch. The task-list poll keeps its own
  // default cadence — the schedule `pollingIntervalMs` governs periodic-task
  // freshness, a separate concern. `fetchAllPages` walks the paginated task
  // list so schedule joins see every definition, not just the first page.
  const tasksQuery = useAppTasks<AppTask>(pluginName, undefined, {
    fetchAllPages: true,
    disablePolling,
  });
  const pluginTaskNames = tasksQuery.data?.items.map((t) => t.name) ?? [];

  const periodicQuery = useQuery<PeriodicTaskResponse[], Error, PeriodicTaskResponse[]>({
    queryKey: PERIODIC_LIST_KEY,
    queryFn: fetchAllPeriodicTasks,
    refetchInterval: disablePolling ? false : pollingIntervalMs,
  });

  // Filter only after both queries have data, otherwise during the initial
  // load the empty `pluginTaskNames` set would briefly hide every periodic
  // task and the panel would flash an empty state before flipping populated.
  const ready = !!tasksQuery.data && !!periodicQuery.data;
  const allowed = new Set(pluginTaskNames);
  const filtered = ready ? (periodicQuery.data ?? []).filter((p) => allowed.has(p.task)) : [];

  return {
    periodicTasks: filtered,
    appTasks: tasksQuery.data?.items ?? [],
    isLoading: tasksQuery.isLoading || periodicQuery.isLoading,
    isError: tasksQuery.isError || periodicQuery.isError,
    error: tasksQuery.error ?? periodicQuery.error,
    refetch: () => {
      void tasksQuery.refetch();
      return periodicQuery.refetch();
    },
  };
}

interface CreateVars {
  taskName: string;
  body: PeriodicTaskCreate;
}

export function useCreateScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation<PeriodicTaskResponse, Error, CreateVars>({
    mutationFn: async ({ taskName, body }) => {
      const { data } = await apiClient.post<PeriodicTaskResponse>(
        `/sep/periodic-tasks/${encodeURIComponent(taskName)}/`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PERIODIC_LIST_KEY });
    },
  });
}

interface UpdateVars {
  id: number;
  body: PeriodicTaskUpdate;
}

export function useUpdateScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation<PeriodicTaskResponse, Error, UpdateVars>({
    mutationFn: async ({ id, body }) => {
      const { data } = await apiClient.put<PeriodicTaskResponse>(`/sep/periodic-tasks/${id}`, body);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PERIODIC_LIST_KEY });
    },
  });
}

export function useDeleteScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: async (id) => {
      await apiClient.delete(`/sep/periodic-tasks/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PERIODIC_LIST_KEY });
    },
  });
}
