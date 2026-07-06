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

import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskHistoryEntry } from '@sep/framework';
import { TaskDetailPage } from './TaskDetailPage';
import { useTaskDetail } from './hooks';
import type { TaskDetailBundle, TaskDetailTask } from './types';

const navigate = vi.fn();
const { stopMutate } = vi.hoisted(() => ({ stopMutate: vi.fn() }));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('./hooks', () => ({
  useTaskDetail: vi.fn(),
}));

vi.mock('./TaskSpecificationSection', () => ({
  TaskSpecificationSection: ({ task }: { task: TaskDetailTask }) => (
    <pre data-testid="task-spec-highlighter">{JSON.stringify(task, null, 2)}</pre>
  ),
}));

vi.mock('@sep/framework', () => ({
  RUNNING_STATUSES: new Set(['running', 'pending']),
  SEP_TABLE_CLASS: 'SepTable',
  ChainDisplay: ({ chainNames }: { chainNames?: readonly string[] }) => (
    <span data-testid="chain-display">{chainNames?.join(', ') ?? '—'}</span>
  ),
  TaskHistoryTable: ({
    data,
    onViewLogs,
    onChainItemClick,
    onStopTask,
  }: {
    data?: TaskHistoryEntry[];
    onViewLogs?: (entry: TaskHistoryEntry) => void;
    onChainItemClick?: (taskName: string) => void;
    onStopTask?: (entry: TaskHistoryEntry) => void;
  }) => (
    <div data-testid="task-history-table">
      <span>rows: {data?.length ?? 0}</span>
      {data?.[0] && onViewLogs ? (
        <button type="button" onClick={() => onViewLogs(data[0])}>
          View logs
        </button>
      ) : null}
      {data?.[0] && onStopTask ? (
        <button type="button" onClick={() => onStopTask(data[0])}>
          Stop {String(data[0].id)}
        </button>
      ) : null}
      {onChainItemClick ? (
        <button type="button" onClick={() => onChainItemClick('chained-task')}>
          Open chain task
        </button>
      ) : null}
    </div>
  ),
  TaskLogViewer: ({ taskHistoryId }: { taskHistoryId: number }) => (
    <div data-testid="task-log-viewer">logs for {taskHistoryId}</div>
  ),
  useStopTaskHistory: () => ({ mutate: stopMutate, isPending: false }),
}));

const mockUseTaskDetail = vi.mocked(useTaskDetail);

const historyEntry = {
  id: 11,
  status: 'running',
  has_logs: true,
  execution_request: {
    task: 'monitor-task',
    target: 'nomad-1',
    meta: {},
    tracking: {},
  },
  task: {
    id: 1,
    name: 'monitor-task',
    backend: 'nomad',
    owner: 'sep',
    is_template: false,
    data: {},
    protected: false,
    alert_on_fail: false,
    anonymize_mask: null,
    created_by: null,
    last_updated_by: null,
  },
} as TaskHistoryEntry;

const detailTask: TaskDetailTask = {
  id: 1,
  name: 'monitor-task',
  data: {},
  backend: 'nomad',
  owner: 'sep',
  is_template: false,
  protected: false,
  alert_on_fail: false,
  deleted_at: null,
  created_at: '2026-05-19T12:00:00Z',
  updated_at: null,
  created_by: 'SYSTEM',
  last_updated_by: null,
  anonymized_entities: [],
};

const detailBundle: TaskDetailBundle = {
  task: detailTask,
  execution_history: {
    items: [
      {
        ...historyEntry,
        id: 10,
        status: 'success',
      },
      historyEntry,
    ],
    total: 2,
    offset: 0,
    limit: 50,
  },
  periodic_summary: [
    {
      id: 1,
      name: 'nightly',
      enabled: true,
      period: '0 0 * * *',
      next_run_at: '2026-05-20T00:00:00Z',
      last_run_at: null,
      total_run_count: 3,
      chain_task_names: ['follow-up-task'],
    },
  ],
  executor_hosts: [{ value: 'nomad-1', label: 'inv-node' }],
};

function renderPage(taskName = 'monitor-task') {
  return render(
    <MemoryRouter initialEntries={[`/tasks/${taskName}`]}>
      <Routes>
        <Route path="/tasks/:taskName" element={<TaskDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('TaskDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTaskDetail.mockReturnValue({
      data: detailBundle,
      isLoading: false,
      error: null,
    } as ReturnType<typeof useTaskDetail>);
  });

  it('renders task metadata and specification', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'monitor-task' })).toBeInTheDocument();
    expect(screen.getByText('Task information')).toBeInTheDocument();
    expect(screen.getByTestId('task-spec-highlighter')).toHaveTextContent('"name": "monitor-task"');
    expect(screen.getByText('SYSTEM')).toBeInTheDocument();
  });

  it('renders running, periodic, and history sections for non-template tasks', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Running' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Periodic schedules' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'History' })).toBeInTheDocument();
    expect(screen.getByText('nightly')).toBeInTheDocument();
    expect(screen.getByTestId('chain-display')).toHaveTextContent('follow-up-task');
    expect(screen.getAllByTestId('task-history-table')).toHaveLength(2);
  });

  it('opens the log viewer dialog when viewing logs', () => {
    renderPage();

    fireEvent.click(screen.getAllByRole('button', { name: 'View logs' })[0]);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByTestId('task-log-viewer')).toHaveTextContent('logs for 11');
  });

  it('navigates to a sibling task detail route when a chain item is clicked', () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Open chain task' }));

    expect(navigate).toHaveBeenCalledWith('../chained-task');
  });

  it('wires the Stop button to the stop-task mutation with the row id', () => {
    renderPage();

    // Running table's first row is the running entry (id 11).
    fireEvent.click(screen.getByRole('button', { name: 'Stop 11' }));

    expect(stopMutate).toHaveBeenCalledWith(11);
  });

  it('hides execution sections for template tasks', () => {
    mockUseTaskDetail.mockReturnValue({
      data: {
        ...detailBundle,
        task: { ...detailBundle.task, is_template: true },
        execution_history: { items: [], total: 0, offset: 0, limit: 50 },
        periodic_summary: [],
      },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useTaskDetail>);

    renderPage('template-task');

    expect(screen.queryByRole('heading', { name: 'Running' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'History' })).not.toBeInTheDocument();
    expect(screen.getByTestId('task-spec-highlighter')).toHaveTextContent('"is_template": true');
  });

  it('shows a loading indicator while the detail bundle loads', () => {
    mockUseTaskDetail.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useTaskDetail>);

    renderPage();

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('shows an error when the detail request fails', () => {
    mockUseTaskDetail.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('detail unavailable'),
    } as ReturnType<typeof useTaskDetail>);

    renderPage();

    expect(screen.getByRole('alert')).toHaveTextContent('detail unavailable');
  });
});
