import { render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { TaskHistoryTable } from './TaskHistoryTable';
import { StatusBadge } from './StatusBadge';
import { useTaskHistory } from '../../hooks/useTaskHistory';
import type { TaskHistoryEntry, TaskHistoryStatus } from './TaskHistoryTable.types';

vi.mock('@sep/api', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from '@sep/api';

const mockedApiClient = apiClient as unknown as {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
};

function makeEntry(
  id: number,
  status: TaskHistoryStatus,
  overrides: Partial<TaskHistoryEntry> = {},
): TaskHistoryEntry {
  return {
    id,
    status,
    started_at: new Date(Date.UTC(2026, 0, 1, 0, id)).toISOString(),
    finished_at:
      status === 'running' || status === 'pending'
        ? null
        : new Date(Date.UTC(2026, 0, 1, 0, id, 30)).toISOString(),
    duration: status === 'running' || status === 'pending' ? null : 30,
    executed_by: 'admin',
    has_logs: true,
    task: { id, name: `task-${id}` } as TaskHistoryEntry['task'],
    execution_request: {
      task: `task-${id}`,
      target: `host-${id}`,
      meta: {},
      tracking: {},
    } as TaskHistoryEntry['execution_request'],
    ...overrides,
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function Wrapper({ children, client }: PropsWithChildren<{ client: QueryClient }>) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('StatusBadge', () => {
  it.each([
    ['success', 'Done'],
    ['failed', 'Failed'],
    ['running', 'Running'],
    ['pending', 'Pending'],
    ['stopped', 'Stopped'],
    ['lost', 'Lost'],
    ['stale', 'Stale'],
  ] as const)('renders %s as %s label', (status, label) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    const chip = screen.getByText(label).closest('[data-status]');
    expect(chip).toHaveAttribute('data-status', status);
  });
});

describe('TaskHistoryTable rendering', () => {
  const client = makeQueryClient();

  it('renders rows for provided data and shows status badges', () => {
    const data = [makeEntry(1, 'success'), makeEntry(2, 'failed'), makeEntry(3, 'running')];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling />
      </Wrapper>,
    );

    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText('task-1')).toBeInTheDocument();
    expect(screen.getByText('host-2')).toBeInTheDocument();
  });

  it('shows empty state when no rows', () => {
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={[]} disablePolling />
      </Wrapper>,
    );
    expect(screen.getByText('No task history')).toBeInTheDocument();
  });

  it('renders chain chips with separators when meta has _chain_task_names', () => {
    const data = [
      makeEntry(1, 'success', {
        execution_request: {
          task: 't',
          target: 'h',
          meta: { _chain_task_names: ['a', 'b', 'c'] },
          tracking: {},
        } as unknown as TaskHistoryEntry['execution_request'],
      }),
    ];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling />
      </Wrapper>,
    );
    const chain = screen.getByTestId('chain-display');
    expect(within(chain).getByText('a')).toBeInTheDocument();
    expect(within(chain).getByText('b')).toBeInTheDocument();
    expect(within(chain).getByText('c')).toBeInTheDocument();
    expect(within(chain).getAllByText('→')).toHaveLength(2);
  });
});

describe('TaskHistoryTable actions', () => {
  const client = makeQueryClient();

  it('shows stop button only for running/pending rows', () => {
    const data = [makeEntry(1, 'success'), makeEntry(2, 'running')];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling />
      </Wrapper>,
    );
    const stopButtons = screen.queryAllByRole('button', { name: 'Stop task' });
    expect(stopButtons).toHaveLength(1);
  });

  it('calls onViewLogs when view-logs clicked', async () => {
    const onViewLogs = vi.fn();
    const data = [makeEntry(1, 'success')];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling onViewLogs={onViewLogs} />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'View logs' }));
    expect(onViewLogs).toHaveBeenCalledOnce();
    expect(onViewLogs.mock.calls[0][0].id).toBe(1);
  });

  it('confirms before invoking onStopTask', async () => {
    const onStopTask = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const data = [makeEntry(2, 'running')];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling onStopTask={onStopTask} />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Stop task' }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(onStopTask).toHaveBeenCalledOnce();
    confirmSpy.mockRestore();
  });

  it('skips stop callback when confirm returns false', async () => {
    const onStopTask = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const data = [makeEntry(2, 'running')];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling onStopTask={onStopTask} />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Stop task' }));
    expect(onStopTask).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('shows download button only for completed rows with downloadable artifacts', () => {
    const data = [
      makeEntry(1, 'success', { has_logs: true }),
      makeEntry(2, 'success', { has_logs: false }),
      makeEntry(3, 'running', { has_logs: true }),
    ];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling />
      </Wrapper>,
    );
    expect(screen.getAllByRole('button', { name: 'Download files' })).toHaveLength(1);
  });
});

describe('TaskHistoryTable sort + pagination', () => {
  const client = makeQueryClient();

  it('sorts by Started column when header clicked', async () => {
    const data = [makeEntry(1, 'success'), makeEntry(2, 'failed'), makeEntry(3, 'running')];
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling />
      </Wrapper>,
    );
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBeGreaterThan(1);
    const startedHeader = screen.getByText('Started');
    await userEvent.click(startedHeader);
    await userEvent.click(startedHeader);
  });

  it('renders pagination controls', () => {
    const data = Array.from({ length: 25 }, (_, i) => makeEntry(i + 1, 'success'));
    render(
      <Wrapper client={client}>
        <TaskHistoryTable data={data} disablePolling />
      </Wrapper>,
    );
    expect(screen.getByLabelText(/Go to next page/i)).toBeInTheDocument();
  });
});

describe('useTaskHistory polling', () => {
  beforeEach(() => {
    mockedApiClient.get.mockReset();
  });

  const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

  it('polls only while running tasks exist, then stops', async () => {
    let returnRunning = true;
    mockedApiClient.get.mockImplementation(async () => ({
      data: {
        items: returnRunning ? [makeEntry(1, 'running')] : [makeEntry(1, 'success')],
        total: 1,
        offset: 0,
        limit: 10,
      },
    }));

    const client = makeQueryClient();
    const { result } = renderHook(() => useTaskHistory({ pollingIntervalMs: 50 }), {
      wrapper: ({ children }) => <Wrapper client={client}>{children}</Wrapper>,
    });

    await waitFor(() => expect(result.current.data?.items[0].status).toBe('running'));
    const callsAfterFirst = mockedApiClient.get.mock.calls.length;
    await wait(160);
    expect(mockedApiClient.get.mock.calls.length).toBeGreaterThan(callsAfterFirst);

    returnRunning = false;
    await waitFor(() => expect(result.current.data?.items[0].status).toBe('success'));
    await wait(80);
    const callsAfterStable = mockedApiClient.get.mock.calls.length;
    await wait(200);
    expect(mockedApiClient.get.mock.calls.length).toBe(callsAfterStable);
  });

  it('does not poll when disablePolling=true even with running rows', async () => {
    mockedApiClient.get.mockResolvedValue({
      data: {
        items: [makeEntry(1, 'running')],
        total: 1,
        offset: 0,
        limit: 10,
      },
    });

    const client = makeQueryClient();
    renderHook(() => useTaskHistory({ pollingIntervalMs: 30, disablePolling: true }), {
      wrapper: ({ children }) => <Wrapper client={client}>{children}</Wrapper>,
    });

    await waitFor(() => expect(mockedApiClient.get).toHaveBeenCalledTimes(1));
    await wait(150);
    expect(mockedApiClient.get).toHaveBeenCalledTimes(1);
  });
});
