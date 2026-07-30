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

import type { Meta, StoryObj } from '@storybook/react-vite';
import { TaskHistoryTable } from './TaskHistoryTable';
import type { TaskHistoryEntry, TaskHistoryStatus } from './TaskHistoryTable.types';

function makeEntry(
  id: number,
  status: TaskHistoryStatus,
  overrides: Partial<TaskHistoryEntry> = {},
): TaskHistoryEntry {
  const startedAt = new Date(Date.UTC(2026, 0, 15, 12, id)).toISOString();
  const finishedAt =
    status === 'running' || status === 'pending'
      ? null
      : new Date(Date.UTC(2026, 0, 15, 12, id, 30)).toISOString();
  const duration = finishedAt ? 30 + id : null;
  return {
    id,
    status,
    display_name: `task-${id}`,
    started_at: startedAt,
    finished_at: finishedAt,
    duration,
    executed_by: 'admin',
    has_logs: status !== 'pending',
    task: {
      id: id,
      name: `task-${id}`,
      // Minimal TaskResponse shape; cast for fixture purposes.
    } as TaskHistoryEntry['task'],
    execution_request: {
      task: `task-${id}`,
      target: `host-${(id % 3) + 1}.example.com`,
      meta: {},
      tracking: {},
    } as unknown as TaskHistoryEntry['execution_request'],
    ...overrides,
  };
}

const ALL_STATUSES: TaskHistoryEntry[] = (
  ['success', 'failed', 'running', 'pending', 'stopped', 'lost', 'stale'] as TaskHistoryStatus[]
).map((status, idx) => makeEntry(idx + 1, status));

const COMPLETED_ONLY: TaskHistoryEntry[] = [
  makeEntry(10, 'success'),
  makeEntry(11, 'failed'),
  makeEntry(12, 'stopped'),
  makeEntry(13, 'success'),
];

const MIXED_RUNNING: TaskHistoryEntry[] = [
  makeEntry(20, 'running'),
  makeEntry(21, 'pending'),
  makeEntry(22, 'success'),
  makeEntry(23, 'failed'),
];

const CHAIN_SCENARIOS: TaskHistoryEntry[] = [
  makeEntry(30, 'success', {
    execution_request: {
      task: 'task-30',
      target: 'host-1.example.com',
      meta: { _chain_task_names: ['task-a', 'task-b', 'task-c'] },
      tracking: {},
    } as unknown as TaskHistoryEntry['execution_request'],
  }),
  makeEntry(31, 'running', {
    execution_request: {
      task: 'task-31',
      target: 'host-2.example.com',
      meta: { _chain_task_names: ['parent', 'child'] },
      tracking: {},
    } as unknown as TaskHistoryEntry['execution_request'],
  }),
  makeEntry(32, 'failed', {
    execution_request: {
      task: 'task-32',
      target: 'host-3.example.com',
      meta: { _chain_depth: 2 },
      tracking: {},
    } as unknown as TaskHistoryEntry['execution_request'],
  }),
];

const meta: Meta<typeof TaskHistoryTable> = {
  title: 'Framework/TaskHistoryTable',
  component: TaskHistoryTable,
  parameters: { layout: 'padded' },
};
export default meta;

type Story = StoryObj<typeof TaskHistoryTable>;

export const AllStatusVariants: Story = {
  args: { data: ALL_STATUSES, disablePolling: true },
};

export const CompletedOnly: Story = {
  args: { data: COMPLETED_ONLY, disablePolling: true },
};

export const MixedRunning: Story = {
  args: { data: MIXED_RUNNING, disablePolling: true },
};

export const ChainDisplays: Story = {
  args: { data: CHAIN_SCENARIOS, disablePolling: true },
};

export const Empty: Story = {
  args: { data: [], disablePolling: true },
};

export const Loading: Story = {
  args: { data: [], isLoading: true, disablePolling: true },
};

export const WithCallbacks: Story = {
  args: {
    data: MIXED_RUNNING,
    disablePolling: true,
    // eslint-disable-next-line no-console
    onViewLogs: (e: TaskHistoryEntry) => console.log('view logs', e.id),
    // eslint-disable-next-line no-console
    onStopTask: (e: TaskHistoryEntry) => console.log('stop', e.id),
    // eslint-disable-next-line no-console
    onDownloadFiles: (e: TaskHistoryEntry) => console.log('download', e.id),
    resolveUserName: (id: string | null | undefined) => (id ? `user:${id}` : ''),
  },
};
