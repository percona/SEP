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

import { useEffect, useMemo } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { ScheduledTasksPanel } from './ScheduledTasksPanel';
import type { PeriodicTaskResponse } from './hooks';

interface StoryArgs {
  periodicTasks: PeriodicTaskResponse[];
  appTasks: { name: string }[];
}

const APP_NAME = 'demo-plugin';

const APP_TASKS = [{ name: 'demo-task' }, { name: 'demo-task-other' }];

const NOW = new Date();

function iso(offsetMinutes: number): string {
  return new Date(NOW.getTime() + offsetMinutes * 60_000).toISOString();
}

const SAMPLE_TASKS: PeriodicTaskResponse[] = [
  {
    id: 1,
    name: 'demo-task @ every-5-min',
    task: 'demo-task',
    enabled: true,
    description: '',
    start_time: null,
    last_run_at: iso(-3),
    next_run_at: iso(2),
    date_changed: iso(-60),
    total_run_count: 42,
    interval: { every: 5, period: 'minutes' },
    crontab: null,
    execute_request: null,
    period: 'every 5 minutes',
  },
  {
    id: 2,
    name: 'demo-task-other @ daily',
    task: 'demo-task-other',
    enabled: false,
    description: '',
    start_time: iso(-1440),
    last_run_at: iso(-720),
    next_run_at: iso(720),
    date_changed: iso(-1500),
    total_run_count: 7,
    interval: null,
    crontab: {
      minute: '0',
      hour: '6',
      day_of_month: '*',
      month_of_year: '*',
      day_of_week: '*',
      timezone: 'UTC',
    },
    execute_request: {
      meta: {} as Record<string, never>,
      chain_task_names: ['demo-task'],
      chain_on_failure: false,
    },
    period: '0 6 * * *',
  },
];

function StoryHarness({ periodicTasks, appTasks }: StoryArgs) {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
    });
    qc.setQueryData(['plugins', APP_NAME, 'tasks'], appTasks);
    qc.setQueryData(['periodic'], periodicTasks);
    return qc;
  }, [periodicTasks, appTasks]);

  useEffect(() => () => queryClient.clear(), [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <ScheduledTasksPanel pluginName={APP_NAME} disablePolling />
    </QueryClientProvider>
  );
}

const meta: Meta<typeof StoryHarness> = {
  title: 'Framework/ScheduledTasksPanel',
  component: StoryHarness,
  parameters: { layout: 'padded' },
};
export default meta;

type Story = StoryObj<typeof StoryHarness>;

export const Empty: Story = {
  args: { periodicTasks: [], appTasks: APP_TASKS },
};

export const Populated: Story = {
  args: { periodicTasks: SAMPLE_TASKS, appTasks: APP_TASKS },
};

export const PopulatedSingle: Story = {
  args: { periodicTasks: [SAMPLE_TASKS[0]], appTasks: APP_TASKS },
};

export const NoAppTasks: Story = {
  args: { periodicTasks: [], appTasks: [] },
};
