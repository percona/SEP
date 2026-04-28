/**
 * Storybook story for TaskHistoryTable.
 *
 * NOTE: Storybook is not yet installed in this monorepo. This file is authored
 * in CSF3 format so it can be picked up automatically when Storybook is wired
 * in. Until then it doubles as a living fixture used by the unit tests.
 */

import type { Meta, StoryObj } from '@storybook/react';
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
    onViewLogs: (e) => console.log('view logs', e.id),
    // eslint-disable-next-line no-console
    onStopTask: (e) => console.log('stop', e.id),
    // eslint-disable-next-line no-console
    onDownloadFiles: (e) => console.log('download', e.id),
    resolveUserName: (id) => (id ? `user:${id}` : ''),
  },
};
