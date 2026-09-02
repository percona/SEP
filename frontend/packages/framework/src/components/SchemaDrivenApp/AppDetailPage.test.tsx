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

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';
import { SnackbarProvider } from 'notistack';
import type { AppSchema } from '@sep/api';
import { AppDetailPage, resolveTabFromSplat, type TaskExecuteAction } from './AppDetailPage';

const mockDeleteMutate = vi.fn();
const mockExecuteMutate = vi.fn();
const mockUseAppTask = vi.fn();
const mockUseAppEntityDetail = vi.fn();
const { stopMutate, useAppTasksMock } = vi.hoisted(() => ({
  stopMutate: vi.fn(),
  useAppTasksMock: vi.fn(),
}));
interface MockStatsResult {
  data: unknown;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
}
const mockUseTaskStats = vi.fn<(...args: unknown[]) => MockStatsResult>(() => ({
  data: undefined,
  isLoading: false,
  isError: false,
}));

function defaultAppTasksResult(items: { name: string }[] = []) {
  return {
    data: { items, pagination: null },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
}

/** Flipped per test to cover the read-only (non-admin) rendering. */
let mockCanMutate = true;

// Manual factory keeps axios out of the resolution graph.
vi.mock('@sep/api', () => ({
  useAuth: () => ({ isAdmin: mockCanMutate, canMutate: mockCanMutate }),
  useAppTask: (...args: unknown[]) => mockUseAppTask(...args),
  // Consumed by ScheduleSummary (via useScheduledTasksForApp) and by ActionBar
  // when capabilities.chaining is set. Default empty list keeps schedule summary
  // in its "Not scheduled" state.
  useAppTasks: (...args: unknown[]) => useAppTasksMock(...args),
  // `useScheduledTasksForApp` (via ScheduleSummary) uses `fetchAllAppListPages`
  // to walk the periodic-task list; an empty page keeps schedule summary in
  // its "Not scheduled" state, matching the previous default.
  fetchAllAppListPages: vi.fn().mockResolvedValue({ items: [], pagination: null }),
  useDeleteAppTask: () => ({
    mutateAsync: mockDeleteMutate,
    isPending: false,
  }),
  useDeleteAppEntity: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAppEntityDetail: (...args: unknown[]) => mockUseAppEntityDetail(...args),
  // Needed by useTaskLogs / useExecutionEvents in the component tree
  getToken: () => null,
  refreshAccessToken: vi.fn(),
  emitUnauthorized: vi.fn(),
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn(),
    defaults: {},
  },
  setTokenProvider: vi.fn(),
  ApiError: class ApiError extends Error {
    status?: number;
    constructor(details: { status?: number; message: string }) {
      super(details.message);
      this.status = details.status;
    }
  },
}));

beforeEach(() => {
  useAppTasksMock.mockReset();
  useAppTasksMock.mockReturnValue(defaultAppTasksResult());
  mockCanMutate = true;
});

vi.mock('../../hooks', () => ({
  useTaskHistoryByName: () => ({ data: { items: [] }, isLoading: false, error: null }),
  useTaskHistoryByNames: () => ({ data: { items: [] }, isLoading: false, error: null }),
  useExecuteTask: () => ({
    mutateAsync: mockExecuteMutate,
    isPending: false,
  }),
  useStopTaskHistory: () => ({ mutate: stopMutate, isPending: false }),
}));

// Execution History tab renders the real TaskHistoryTable; stub it to capture the wired
// onStopTask handler (no other test exercises the Execution History tab / this component).
vi.mock('../TaskHistoryTable', async (importOriginal) => ({
  // Keep the real TaskHistoryStatusBadge + isTaskHistoryStatus (now used by the
  // detail header); only the table itself is stubbed.
  ...(await importOriginal<typeof import('../TaskHistoryTable')>()),
  TaskHistoryTable: ({ onStopTask }: { onStopTask?: (entry: { id: number }) => void }) =>
    onStopTask ? (
      <button type="button" onClick={() => onStopTask({ id: 7 })}>
        Stop row
      </button>
    ) : (
      <div data-testid="task-history-table" />
    ),
}));

vi.mock('../../hooks/useTaskStats', () => ({
  useTaskStats: (taskName?: string, enabled?: boolean) => mockUseTaskStats(taskName, enabled),
}));

vi.mock('./DetailSyntaxHighlighter', () => ({
  default: ({ value, language }: { value: unknown; language: string }) => (
    <pre data-testid="detail-syntax-highlighter" data-language={language}>
      {String(value)}
    </pre>
  ),
}));

const schema: AppSchema = {
  pluginName: 'checksums',
  display_name: 'Checksum',
  description: 'Test',
  capabilities: { scheduling: true },
  list_view: {
    columns: [
      { key: 'name', label: 'Name' },
      { key: 'status', label: 'Status', format: 'status' },
    ],
    default_sort: '-id',
  },
  formSchema: { sections: [] },
} as unknown as AppSchema;

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={makeClient()}>
      <SnackbarProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/apps/:plugin/task/:id/*"
              element={<AppDetailPage schema={schema} pluginName="checksums" />}
            />
            <Route path="/apps/:plugin" element={<div>list page</div>} />
          </Routes>
        </MemoryRouter>
      </SnackbarProvider>
    </QueryClientProvider>,
  );
}

describe('AppDetailPage — detail_view sections', () => {
  function executionSchema(overrides: Partial<AppSchema> = {}): AppSchema {
    return {
      pluginName: 'checksums',
      display_name: 'Checksum',
      description: 'Test',
      capabilities: {},
      list_view: {
        columns: [
          { key: 'name', label: 'Name' },
          { key: 'status', label: 'Status', format: 'status' },
        ],
        default_sort: '-id',
      },
      formSchema: { sections: [] },
      detail_view: {
        sections: [
          {
            title: 'Execution',
            fields: [
              { path: 'data.meta.command', label: 'Command' },
              { path: 'data.meta.args', label: 'Args' },
              { path: 'data.meta.target', label: 'Target' },
            ],
          },
        ],
      },
      ...overrides,
    } as unknown as AppSchema;
  }

  it('renders a section with each labelled field resolved from the task', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: {
          meta: {
            command: 'pt-table-checksum',
            args: '--foo',
            target: 'pmm',
          },
        },
      },
      isLoading: false,
    });

    renderWithSchema(executionSchema());

    expect(screen.getByRole('heading', { name: 'Execution' })).toBeInTheDocument();
    expect(screen.getByText('pt-table-checksum')).toBeInTheDocument();
    expect(screen.getByText('--foo')).toBeInTheDocument();
    expect(screen.getByText('pmm')).toBeInTheDocument();
  });

  it('skips fields whose path resolves to undefined', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: { meta: { command: 'pt-table-checksum' } },
      },
      isLoading: false,
    });

    renderWithSchema(executionSchema());

    expect(screen.getByText('Command')).toBeInTheDocument();
    expect(screen.queryByText('Args')).toBeNull();
    expect(screen.queryByText('Target')).toBeNull();
  });

  it('skips fields whose path resolves to an empty string', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: {
          meta: { command: '', args: '--foo', target: 'pmm' },
        },
      },
      isLoading: false,
    });

    renderWithSchema(executionSchema());

    expect(screen.queryByText('Command')).toBeNull();
    expect(screen.getByText('Args')).toBeInTheDocument();
  });

  it('hides the whole section when every field resolves empty', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed', data: {} },
      isLoading: false,
    });

    renderWithSchema(executionSchema());

    expect(screen.queryByRole('heading', { name: 'Execution' })).toBeNull();
  });

  it('renders multiple sections in declared order', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: {
          meta: { command: 'cmd', args: '--foo', target: 'pmm' },
          parent: 'parent-task',
        },
      },
      isLoading: false,
    });

    renderWithSchema(
      executionSchema({
        detail_view: {
          sections: [
            {
              title: 'Execution',
              fields: [{ path: 'data.meta.command', label: 'Command' }],
            },
            {
              title: 'Chain',
              fields: [{ path: 'data.parent', label: 'Parent' }],
            },
          ],
        },
      } as unknown as AppSchema),
    );

    const headings = screen.getAllByRole('heading', { level: 6 }).map((h) => h.textContent);
    const execIdx = headings.indexOf('Execution');
    const chainIdx = headings.indexOf('Chain');
    expect(execIdx).toBeGreaterThanOrEqual(0);
    expect(chainIdx).toBeGreaterThanOrEqual(0);
    expect(execIdx).toBeLessThan(chainIdx);
  });

  it('does not render any section cards when detail_view is undefined', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: { meta: { command: 'cmd' } },
      },
      isLoading: false,
    });

    renderWithSchema(executionSchema({ detail_view: undefined } as AppSchema));

    expect(screen.queryByRole('heading', { name: 'Execution' })).toBeNull();
  });

  it('passes DetailField.highlight through to the syntax highlighter', async () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: { meta: { command: 'SELECT 1' } },
      },
      isLoading: false,
    });

    renderWithSchema(
      executionSchema({
        detail_view: {
          sections: [
            {
              title: 'Execution',
              fields: [{ path: 'data.meta.command', label: 'Command', highlight: 'sql' }],
            },
          ],
        },
      } as unknown as AppSchema),
    );

    const hl = await screen.findByTestId('detail-syntax-highlighter');
    expect(hl.getAttribute('data-language')).toBe('sql');
    expect(hl.textContent).toBe('SELECT 1');
  });

  it('passes DetailField.highlight="yaml" through to the syntax highlighter', async () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: { meta: { config: 'foo: bar' } },
      },
      isLoading: false,
    });

    renderWithSchema(
      executionSchema({
        detail_view: {
          sections: [
            {
              title: 'Execution',
              fields: [{ path: 'data.meta.config', label: 'Config', highlight: 'yaml' }],
            },
          ],
        },
      } as unknown as AppSchema),
    );

    const hl = await screen.findByTestId('detail-syntax-highlighter');
    expect(hl.getAttribute('data-language')).toBe('yaml');
    expect(hl.textContent).toBe('foo: bar');
  });

  it('renders boolean false and numeric zero leaves', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: { meta: { command: false, args: 0 } },
      },
      isLoading: false,
    });

    renderWithSchema(executionSchema());

    expect(screen.getByText('No')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
  });
});

describe('AppDetailPage — TaskOverviewDetailField object values', () => {
  it('renders a nested object extra field via the JSON syntax highlighter, not a raw <pre> dump', async () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        config: { host: 'db1', port: 3306 },
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    const hl = await screen.findByTestId('detail-syntax-highlighter');
    expect(hl.getAttribute('data-language')).toBe('json');
    // The Config label comes from formatLabel() on the extra key.
    expect(screen.getByText('Config')).toBeInTheDocument();
  });

  it('renders an array extra field via the JSON syntax highlighter', async () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        tags: ['alpha', 'beta'],
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    const hl = await screen.findByTestId('detail-syntax-highlighter');
    expect(hl.getAttribute('data-language')).toBe('json');
    expect(screen.getByText('Tags')).toBeInTheDocument();
  });

  it('renders an empty object extra field via the highlighter rather than hiding it', async () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        config: {},
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    const hl = await screen.findByTestId('detail-syntax-highlighter');
    expect(hl.getAttribute('data-language')).toBe('json');
  });
});

describe('resolveTabFromSplat', () => {
  it('returns overview when splat is undefined', () => {
    expect(resolveTabFromSplat(undefined)).toBe('overview');
  });

  it('returns overview when splat is empty', () => {
    expect(resolveTabFromSplat('')).toBe('overview');
  });

  it('returns logs when splat is "logs"', () => {
    expect(resolveTabFromSplat('logs')).toBe('logs');
  });

  it('returns logs when splat has trailing slash', () => {
    expect(resolveTabFromSplat('logs/')).toBe('logs');
  });

  it('returns logs for nested logs sub-paths', () => {
    expect(resolveTabFromSplat('logs/123')).toBe('logs');
  });

  it('returns overview for non-logs paths', () => {
    expect(resolveTabFromSplat('overview')).toBe('overview');
    expect(resolveTabFromSplat('something-else')).toBe('overview');
  });
});

describe('AppDetailPage execute flow', () => {
  it('confirms then calls execute mutation on success', async () => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockResolvedValue({ id: 99 });
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK');

    await userEvent.click(screen.getByTestId('plugin-task-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() => expect(mockExecuteMutate).toHaveBeenCalledWith({ taskName: 'FECHK' }));
  });

  it('shows error snackbar and keeps dialog open on execute failure', async () => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockRejectedValue(new Error('Execute failed'));
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK');

    await userEvent.click(screen.getByTestId('plugin-task-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() => expect(screen.getByText('Execute failed')).toBeInTheDocument());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('closes dialog without calling execute when cancelled', async () => {
    mockExecuteMutate.mockReset();
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK');

    await userEvent.click(screen.getByTestId('plugin-task-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mockExecuteMutate).not.toHaveBeenCalled();
  });

  it('executes a selected derived task when custom execute actions are provided', async () => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockResolvedValue({ id: 99 });
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'pbm-backup',
        status: 'completed',
        derived_tasks: [{ name: 'pbm-backup-logical', backup_type: 'pbm_logical', status: null }],
      },
      isLoading: false,
    });

    render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/apps/backup_mongo/task/pbm-backup']}>
            <Routes>
              <Route
                path="/apps/:plugin/task/:id/*"
                element={
                  <AppDetailPage
                    schema={schema}
                    pluginName="backup_mongo"
                    getTaskExecuteActions={(task) => [
                      {
                        label: 'Sync Config',
                        taskName: String(task.name),
                        testId: 'backup-mongo-sync-config',
                      },
                      {
                        label: 'Run Logical Backup',
                        taskName: 'pbm-backup-logical',
                        testId: 'backup-mongo-logical-backup',
                      },
                    ]}
                  />
                }
              />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByTestId('backup-mongo-logical-backup'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() =>
      expect(mockExecuteMutate).toHaveBeenCalledWith({ taskName: 'pbm-backup-logical' }),
    );
  });

  it('forwards executeBody from custom execute actions to the mutation', async () => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockResolvedValue({ id: 99 });
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'my-alter', status: 'completed' },
      isLoading: false,
    });

    const executeBody = {
      chain_task_names: ['my-alter'],
      chain_on_failure: false,
    };

    render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/apps/alters/task/my-alter']}>
            <Routes>
              <Route
                path="/apps/:plugin/task/:id/*"
                element={
                  <AppDetailPage
                    schema={schema}
                    pluginName="alters"
                    getTaskExecuteActions={() => [
                      {
                        label: 'Pre-checks',
                        taskName: 'my-alter-pre-checks',
                        testId: 'alters-pre-checks-execute',
                        executeBody,
                      },
                    ]}
                  />
                }
              />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByTestId('alters-pre-checks-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() =>
      expect(mockExecuteMutate).toHaveBeenCalledWith({
        taskName: 'my-alter-pre-checks',
        executeBody,
      }),
    );
  });
});

describe('AppDetailPage — execute chain composition', () => {
  const backupMongoExecuteActions = (task: Record<string, unknown>): TaskExecuteAction[] => [
    {
      label: 'Sync Config',
      taskName: String(task.name),
      testId: 'backup-mongo-sync-config',
    },
    {
      label: 'Run Logical Backup',
      taskName: 'pbm-backup-logical',
      testId: 'backup-mongo-logical-backup',
    },
  ];

  beforeEach(() => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockResolvedValue({ id: 99 });
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    useAppTasksMock.mockReturnValue(
      defaultAppTasksResult([{ name: 'FECHK' }, { name: 'other-task' }]),
    );
  });

  async function addTaskToChain(dialog: HTMLElement, taskName: string) {
    const user = userEvent.setup();
    await user.click(within(dialog).getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: taskName }));
  }

  function renderBackupMongoChainPage() {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'pbm-backup',
        status: 'completed',
        derived_tasks: [{ name: 'pbm-backup-logical', backup_type: 'pbm_logical', status: null }],
      },
      isLoading: false,
    });
    useAppTasksMock.mockReturnValue(
      defaultAppTasksResult([
        { name: 'pbm-backup' },
        { name: 'pbm-backup-logical' },
        { name: 'other-task' },
      ]),
    );
    return renderWithSchema(makeSchema({ chaining: true }), {
      pluginName: 'backup_mongo',
      path: '/apps/backup_mongo/task/pbm-backup',
      getTaskExecuteActions: backupMongoExecuteActions,
    });
  }

  it('renders ChainBuilder when chaining is true', async () => {
    renderWithSchema(makeSchema({ chaining: true }));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    expect(await screen.findByTestId('chain-builder')).toBeInTheDocument();
    expect(useAppTasksMock).toHaveBeenCalledWith(
      'checksums',
      undefined,
      expect.objectContaining({ fetchAllPages: true, enabled: true }),
    );
  });

  it('shows a loading state while chainable tasks are fetching', async () => {
    useAppTasksMock.mockReturnValue({
      ...defaultAppTasksResult(),
      data: undefined,
      isLoading: true,
    });
    renderWithSchema(makeSchema({ chaining: true }));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    expect(await screen.findByTestId('chain-tasks-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('chain-builder')).not.toBeInTheDocument();
  });

  it('shows an error when chainable tasks fail to load', async () => {
    useAppTasksMock.mockReturnValue({
      ...defaultAppTasksResult(),
      data: undefined,
      isError: true,
      error: new Error('network down'),
    });
    renderWithSchema(makeSchema({ chaining: true }));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    expect(await screen.findByTestId('chain-tasks-error')).toHaveTextContent(/network down/);
    expect(screen.queryByTestId('chain-builder')).not.toBeInTheDocument();
  });

  it('does not render ChainBuilder when chaining is false', async () => {
    renderWithSchema(makeSchema({ chaining: false }));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    await screen.findByRole('dialog');
    expect(screen.queryByTestId('chain-builder')).not.toBeInTheDocument();
  });

  it('does not render ChainBuilder when chaining is absent', async () => {
    renderWithSchema(makeSchema(undefined));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    await screen.findByRole('dialog');
    expect(screen.queryByTestId('chain-builder')).not.toBeInTheDocument();
  });

  it('does not enable the app-tasks fetch when chaining is disabled', async () => {
    renderWithSchema(makeSchema({ chaining: false }));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    await screen.findByRole('dialog');
    expect(useAppTasksMock).toHaveBeenCalledWith(
      'checksums',
      undefined,
      expect.objectContaining({ enabled: false }),
    );
  });

  it('posts composed chain_task_names and chain_on_failure on confirm', async () => {
    const user = userEvent.setup();
    renderWithSchema(makeSchema({ chaining: true }));
    await user.click(screen.getByTestId('plugin-task-execute'));
    const dialog = await screen.findByRole('dialog');
    await addTaskToChain(dialog, 'other-task');
    await user.click(within(dialog).getByTestId('chain-on-failure-checkbox'));
    await user.click(within(dialog).getByTestId('plugin-task-execute-confirm'));
    await waitFor(() =>
      expect(mockExecuteMutate).toHaveBeenCalledWith({
        taskName: 'FECHK',
        executeBody: {
          chain_task_names: ['other-task'],
          chain_on_failure: true,
        },
      }),
    );
  });

  it('omits chain fields when the chain is empty', async () => {
    renderWithSchema(makeSchema({ chaining: true }));
    await userEvent.click(screen.getByTestId('plugin-task-execute'));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByTestId('chain-builder')).toBeInTheDocument();
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));
    await waitFor(() => expect(mockExecuteMutate).toHaveBeenCalled());
    const body = mockExecuteMutate.mock.calls.at(-1)?.[0] as {
      taskName: string;
      executeBody?: Record<string, unknown>;
    };
    expect(body.taskName).toBe('FECHK');
    expect(body.executeBody?.chain_task_names).toBeUndefined();
    expect(body.executeBody?.chain_on_failure).toBeUndefined();
  });

  it('merges chain into existing action executeBody', async () => {
    const user = userEvent.setup();
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'my-alter', status: 'completed' },
      isLoading: false,
    });
    useAppTasksMock.mockReturnValue(
      defaultAppTasksResult([{ name: 'my-alter-pre-checks' }, { name: 'other-task' }]),
    );

    renderWithSchema(makeSchema({ chaining: true }), {
      pluginName: 'alters',
      path: '/apps/alters/task/my-alter',
      getTaskExecuteActions: () => [
        {
          label: 'Pre-checks',
          taskName: 'my-alter-pre-checks',
          testId: 'alters-pre-checks-execute',
          executeBody: { eta: '2099-01-01T00:00:00Z' },
        },
      ],
    });

    await user.click(screen.getByTestId('alters-pre-checks-execute'));
    const dialog = await screen.findByRole('dialog');
    await addTaskToChain(dialog, 'other-task');
    await user.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() =>
      expect(mockExecuteMutate).toHaveBeenCalledWith({
        taskName: 'my-alter-pre-checks',
        executeBody: {
          eta: '2099-01-01T00:00:00Z',
          chain_task_names: ['other-task'],
          chain_on_failure: false,
        },
      }),
    );
  });

  it('keys currentTaskName to the pending execute action, not the page task', async () => {
    const user = userEvent.setup();
    renderBackupMongoChainPage();

    await user.click(screen.getByTestId('backup-mongo-logical-backup'));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByTestId('chain-builder')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('combobox'));
    const logicalOption = await screen.findByRole('option', { name: 'pbm-backup-logical' });
    expect(logicalOption).toHaveAttribute('aria-disabled', 'true');
    const pageTaskOption = await screen.findByRole('option', { name: 'pbm-backup' });
    expect(pageTaskOption).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('resets chain when opening a different execute action', async () => {
    const user = userEvent.setup();
    renderBackupMongoChainPage();

    await user.click(screen.getByTestId('backup-mongo-sync-config'));
    let dialog = await screen.findByRole('dialog');
    await addTaskToChain(dialog, 'other-task');
    expect(within(dialog).getByTestId('chain-sequence')).toHaveTextContent('other-task');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await user.click(screen.getByTestId('backup-mongo-logical-backup'));
    dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByTestId('chain-builder')).toBeInTheDocument();
    expect(within(dialog).queryByTestId('chain-sequence')).not.toBeInTheDocument();
  });

  it('keeps dialog open with composed chain when execute fails', async () => {
    const user = userEvent.setup();
    mockExecuteMutate.mockRejectedValue(new Error('Chain contains a cycle'));
    renderWithSchema(makeSchema({ chaining: true }));
    await user.click(screen.getByTestId('plugin-task-execute'));
    const dialog = await screen.findByRole('dialog');
    await addTaskToChain(dialog, 'other-task');
    await user.click(within(dialog).getByTestId('plugin-task-execute-confirm'));
    await screen.findByText(/Chain contains a cycle/);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(within(screen.getByRole('dialog')).getByTestId('chain-sequence')).toHaveTextContent(
      'other-task',
    );
  });
});

function renderWithSchema(
  customSchema: AppSchema,
  options: {
    path?: string;
    pluginName?: string;
    getTaskExecuteActions?: (task: Record<string, unknown>) => TaskExecuteAction[] | undefined;
  } = {},
) {
  const pluginName = options.pluginName ?? 'checksums';
  const path = options.path ?? `/apps/${pluginName}/task/FECHK`;
  return render(
    <QueryClientProvider client={makeClient()}>
      <SnackbarProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/apps/:plugin/task/:id/*"
              element={
                <AppDetailPage
                  schema={customSchema}
                  pluginName={pluginName}
                  getTaskExecuteActions={options.getTaskExecuteActions}
                />
              }
            />
            <Route path="/apps/:plugin" element={<div>list page</div>} />
          </Routes>
        </MemoryRouter>
      </SnackbarProvider>
    </QueryClientProvider>,
  );
}

function makeSchema(capabilities: Record<string, boolean> | undefined): AppSchema {
  return {
    pluginName: 'checksums',
    display_name: 'Checksum',
    description: 'Test',
    capabilities,
    list_view: {
      columns: [
        { key: 'name', label: 'Name' },
        { key: 'status', label: 'Status', format: 'status' },
      ],
      default_sort: '-id',
    },
    formSchema: { sections: [] },
  } as unknown as AppSchema;
}

const POPULATED_STATS = {
  engine: 'nomad',
  total: 5,
  status: { pass: 4, fail: 1 },
  duration: { average_seconds: 1.234, last_seconds: 0.987, total_seconds: 6.17 },
  last_finished_at: new Date(Date.now() - 60_000).toISOString(),
};

describe('AppDetailPage — StatsCard integration', () => {
  beforeEach(() => {
    mockUseTaskStats.mockReset();
    mockUseTaskStats.mockReturnValue({ data: undefined, isLoading: false, isError: false });
  });

  it('renders the StatsCard when capabilities.stats is true', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    mockUseTaskStats.mockReturnValue({
      data: POPULATED_STATS,
      isLoading: false,
      isError: false,
    });
    renderWithSchema(makeSchema({ stats: true }));
    expect(screen.getByText('Executions')).toBeInTheDocument();
  });

  it('forwards both taskName and enabled to useTaskStats', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    renderWithSchema(makeSchema({ stats: true }));
    expect(mockUseTaskStats).toHaveBeenCalled();
    const lastCall = mockUseTaskStats.mock.calls.at(-1) ?? [];
    // Guard against the prior mock that dropped every arg after the first,
    // which hid regressions around the ``enabled`` flag.
    expect(lastCall[0]).toBe('FECHK');
    expect(lastCall[1]).toBe(true);
  });

  it('does not render the StatsCard when capabilities.stats is false', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    renderWithSchema(makeSchema({ stats: false }));
    expect(screen.queryByText('Executions')).toBeNull();
    expect(mockUseTaskStats).not.toHaveBeenCalled();
  });

  it('does not render the StatsCard when capabilities.stats is absent', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    renderWithSchema(makeSchema({}));
    expect(screen.queryByText('Executions')).toBeNull();
    expect(mockUseTaskStats).not.toHaveBeenCalled();
  });

  it('does not render the StatsCard when capabilities is undefined', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    renderWithSchema(makeSchema(undefined));
    expect(screen.queryByText('Executions')).toBeNull();
    expect(mockUseTaskStats).not.toHaveBeenCalled();
  });

  it('does not render the StatsCard when task.name is missing', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, status: 'completed' },
      isLoading: false,
    });
    renderWithSchema(makeSchema({ stats: true }));
    // Hook is invoked but with undefined name, so it disables itself; the card
    // returns null before rendering the section header.
    expect(screen.queryByText('Executions')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Stats' })).toBeNull();
  });

  it('does not render the StatsCard when task.name is numeric', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 42, status: 'completed' },
      isLoading: false,
    });
    renderWithSchema(makeSchema({ stats: true }));
    expect(screen.queryByText('Executions')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Stats' })).toBeNull();
  });

  it('renders empty state when stats.total === 0', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    mockUseTaskStats.mockReturnValue({
      data: {
        engine: 'nomad',
        total: 0,
        status: { pass: 0, fail: 0 },
        duration: { average_seconds: null, last_seconds: null, total_seconds: null },
        last_finished_at: null,
      },
      isLoading: false,
      isError: false,
    });
    renderWithSchema(makeSchema({ stats: true }));
    expect(screen.getByText('No execution history yet')).toBeInTheDocument();
    expect(screen.queryByText('Executions')).toBeNull();
  });

  it('keeps the Task information section when stats query errors', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    mockUseTaskStats.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('boom'),
    });
    renderWithSchema(makeSchema({ stats: true }));
    expect(screen.getByText('Task information')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load execution stats');
  });
});

describe('AppDetailPage — tabs', () => {
  it('labels the history tab Execution History', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK');

    expect(screen.getByRole('tab', { name: 'Execution History' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Logs' })).toBeNull();
  });
});

describe('AppDetailPage — Execution History tab stop wiring', () => {
  beforeEach(() => {
    stopMutate.mockReset();
  });

  it('wires the Execution History tab table Stop action to the stop-task mutation with the row id', async () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'running' },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK/logs');

    await userEvent.click(await screen.findByRole('button', { name: 'Stop row' }));

    expect(stopMutate).toHaveBeenCalledWith(7);
  });
});

describe('AppDetailPage — PII Anonymization section', () => {
  it('renders PII section with entity chips when capability is true and entities present', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        anonymized_entities: ['EMAIL_ADDRESS', 'IP_ADDRESS'],
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({ pii_anonymization: true }));

    expect(screen.getByRole('heading', { name: 'PII Anonymization' })).toBeInTheDocument();
    const chips = screen.getAllByTestId('pii-entity-chip');
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent('EMAIL ADDRESS');
    expect(chips[1]).toHaveTextContent('IP ADDRESS');
  });

  it('renders empty state message when capability is true but entities list is empty', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed', anonymized_entities: [] },
      isLoading: false,
    });

    renderWithSchema(makeSchema({ pii_anonymization: true }));

    expect(screen.getByRole('heading', { name: 'PII Anonymization' })).toBeInTheDocument();
    expect(screen.getByText('No PII entities configured for anonymization.')).toBeInTheDocument();
  });

  it('does not render PII section when capability is false', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        anonymized_entities: ['EMAIL_ADDRESS'],
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({ pii_anonymization: false }));

    expect(screen.queryByRole('heading', { name: 'PII Anonymization' })).toBeNull();
  });

  it('does not render PII section when capability is absent', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        anonymized_entities: ['EMAIL_ADDRESS'],
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    expect(screen.queryByRole('heading', { name: 'PII Anonymization' })).toBeNull();
  });

  it('does not render PII section when capabilities is undefined', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        anonymized_entities: ['EMAIL_ADDRESS'],
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema(undefined));

    expect(screen.queryByRole('heading', { name: 'PII Anonymization' })).toBeNull();
  });

  it('suppresses anonymize_mask and anonymized_entities from the Task information extras', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        anonymize_mask: 2,
        anonymized_entities: ['EMAIL_ADDRESS'],
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({ pii_anonymization: true }));

    expect(screen.queryByText('Anonymize Mask')).toBeNull();
    expect(screen.queryByText('Anonymized Entities')).toBeNull();
  });
});

describe('AppDetailPage — overview_hidden_fields', () => {
  function schemaWithHidden(overview_hidden_fields?: string[]): AppSchema {
    return {
      pluginName: 'checksums',
      display_name: 'Checksum',
      description: 'Test',
      capabilities: {},
      list_view: {
        columns: [
          { key: 'name', label: 'Name' },
          { key: 'status', label: 'Status', format: 'status' },
        ],
        default_sort: '-name',
        ...(overview_hidden_fields !== undefined ? { overview_hidden_fields } : {}),
      },
      formSchema: { sections: [] },
    } as unknown as AppSchema;
  }

  it('hides baseline keys (id, backend, data, etc.) when overview_hidden_fields is absent', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        backend: 'nomad',
        data: {},
        extra_visible: 'hello',
      },
      isLoading: false,
    });

    renderWithSchema(schemaWithHidden());

    expect(screen.queryByText('Id')).toBeNull();
    expect(screen.queryByText('Backend')).toBeNull();
    expect(screen.queryByText('Data')).toBeNull();
    // A non-hidden extra still renders
    expect(screen.getByText('Extra Visible')).toBeInTheDocument();
  });

  it('hides a schema-declared key in addition to the baseline', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed', foo: 'secret', extra_visible: 'hello' },
      isLoading: false,
    });

    renderWithSchema(schemaWithHidden(['foo']));

    expect(screen.queryByText('Foo')).toBeNull();
    // Unrelated extra field still renders
    expect(screen.getByText('Extra Visible')).toBeInTheDocument();
  });

  it('hides entity-level overview_hidden_fields in multi-entity detail page', () => {
    function multiEntitySchemaWithHidden(overview_hidden_fields?: string[]): AppSchema {
      return {
        pluginName: 'inventory',
        display_name: 'Inventory',
        description: 'Test',
        capabilities: {},
        entities: [
          {
            name: 'services',
            display_name: 'Services',
            description: 'Service entities',
            forms: [],
            list_view: {
              columns: [
                { key: 'name', label: 'Name' },
                { key: 'status', label: 'Status', format: 'status' },
              ],
              default_sort: '-name',
              ...(overview_hidden_fields !== undefined ? { overview_hidden_fields } : {}),
            },
          },
        ],
        list_view: {
          columns: [{ key: 'name', label: 'Name' }],
          default_sort: '-name',
        },
        formSchema: { sections: [] },
      } as unknown as AppSchema;
    }

    mockUseAppEntityDetail.mockReturnValue({
      data: {
        id: 1,
        name: 'mysql-01',
        status: 'active',
        foo: 'secret',
        extra_visible: 'hello',
      },
      isLoading: false,
      error: null,
    });

    const customSchema = multiEntitySchemaWithHidden(['foo']);
    render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/apps/inventory/services/1']}>
            <Routes>
              <Route
                path="/apps/:plugin/:entityName/:id/*"
                element={<AppDetailPage schema={customSchema} pluginName="inventory" />}
              />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );

    expect(screen.queryByText('Foo')).toBeNull();
    expect(screen.queryByText('foo')).toBeNull();
    // Unrelated extra field still renders
    expect(screen.getByText('extra_visible')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('hides a list_view.columns entry named in overview_hidden_fields (multi-entity)', () => {
    function multiEntitySchemaWithHiddenColumn(): AppSchema {
      return {
        pluginName: 'inventory',
        display_name: 'Inventory',
        description: 'Test',
        capabilities: {},
        entities: [
          {
            name: 'services',
            display_name: 'Services',
            description: 'Service entities',
            forms: [],
            list_view: {
              columns: [
                { key: 'name', label: 'Name' },
                { key: 'status', label: 'Status', format: 'status' },
              ],
              default_sort: '-name',
              overview_hidden_fields: ['status'],
            },
          },
        ],
        list_view: {
          columns: [{ key: 'name', label: 'Name' }],
          default_sort: '-name',
        },
        formSchema: { sections: [] },
      } as unknown as AppSchema;
    }

    mockUseAppEntityDetail.mockReturnValue({
      data: { id: 1, name: 'mysql-01', status: 'active' },
      isLoading: false,
      error: null,
    });

    render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/apps/inventory/services/1']}>
            <Routes>
              <Route
                path="/apps/:plugin/:entityName/:id/*"
                element={
                  <AppDetailPage
                    schema={multiEntitySchemaWithHiddenColumn()}
                    pluginName="inventory"
                  />
                }
              />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );

    // The Status column is suppressed from the detail body; Name still renders.
    expect(screen.queryByText('Status')).toBeNull();
    expect(screen.getByText('Name')).toBeInTheDocument();
  });
});

describe('AppDetailPage — header de-duplication', () => {
  it('does not repeat the header task name or status chip in the Task information card', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed', extra_visible: 'hello' },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    // The header owns name + status; the card must not re-list their labels.
    const card = screen.getByText('Task information').closest('div') as HTMLElement;
    expect(within(card).queryByText('Name')).toBeNull();
    expect(within(card).queryByText('Status')).toBeNull();

    // The task name value appears exactly once (header only).
    expect(screen.getAllByText('FECHK')).toHaveLength(1);
    // Genuinely-distinct extra fields still render in the card.
    expect(within(card).getByText('Extra Visible')).toBeInTheDocument();
  });

  it('still lists status in the card when the header omits the chip (non-string status)', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 42 },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    // Header renders the chip only for string status, so status stays visible
    // in the card to avoid dropping a value nothing else surfaces.
    const card = screen.getByText('Task information').closest('div') as HTMLElement;
    expect(within(card).getByText('Status')).toBeInTheDocument();
  });

  it('still lists name in the card when the header falls back to the id (non-string name)', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 42, status: 'completed' },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    // Header shows task.name only when it's a string; otherwise it falls back
    // to the route id, so a non-string name must remain visible in the card.
    const card = screen.getByText('Task information').closest('div') as HTMLElement;
    expect(within(card).getByText('Name')).toBeInTheDocument();
    expect(within(card).getByText('42')).toBeInTheDocument();
  });
});

describe('AppDetailPage — header status badge', () => {
  it('renders the shared status badge for the single-task header, with running in the animated state', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'running' },
      isLoading: false,
    });

    const { container } = renderAt('/apps/checksums/task/FECHK');

    // Mapped label + data-status attribute from TaskHistoryStatusBadge, not the
    // raw 'running' string of the removed inline chip.
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(container.querySelector('[data-status="running"]')).toBeInTheDocument();
  });

  it('falls back to a plain chip (no badge) for an unrecognized status', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'weird' },
      isLoading: false,
    });

    const { container } = renderAt('/apps/checksums/task/FECHK');

    // Unrecognized string still shows the raw value in a plain header chip so
    // status never silently disappears, but without the badge's data-status
    // attribute. (The Overview field also echoes the raw value, hence getAll.)
    expect(screen.getAllByText('weird').length).toBeGreaterThan(0);
    expect(container.querySelector('.MuiChip-root')).toHaveTextContent('weird');
    expect(container.querySelector('[data-status]')).toBeNull();
  });

  it('renders the shared status badge for the multi-entity detail header', () => {
    const multiSchema = {
      pluginName: 'inventory',
      display_name: 'Inventory',
      description: 'Test',
      capabilities: {},
      entities: [
        {
          name: 'services',
          display_name: 'Services',
          description: 'Service entities',
          forms: [],
          list_view: {
            columns: [
              { key: 'name', label: 'Name' },
              { key: 'status', label: 'Status', format: 'status' },
            ],
            default_sort: '-name',
          },
        },
      ],
      list_view: { columns: [{ key: 'name', label: 'Name' }], default_sort: '-name' },
      formSchema: { sections: [] },
    } as unknown as AppSchema;

    mockUseAppEntityDetail.mockReturnValue({
      data: { id: 1, name: 'mysql-01', status: 'failed' },
      isLoading: false,
      error: null,
    });

    const { container } = render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/apps/inventory/services/1']}>
            <Routes>
              <Route
                path="/apps/:plugin/:entityName/:id/*"
                element={<AppDetailPage schema={multiSchema} pluginName="inventory" />}
              />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(container.querySelector('[data-status="failed"]')).toBeInTheDocument();
  });
});

describe('AppDetailPage — Edit affordance', () => {
  it('enables Edit and links to the edit route when the task has a stored form', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        data: { _form: { task_name: 'FECHK' } },
      },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK');

    const edit = screen.getByTestId('plugin-task-edit');
    expect(edit).not.toBeDisabled();
    expect(edit).toHaveAttribute('href', '/apps/checksums/task/FECHK/edit');
  });

  it('disables Edit for a task with no stored form (legacy or legacy-form-created)', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed', data: { meta: {} } },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/FECHK');

    expect(screen.getByTestId('plugin-task-edit')).toBeDisabled();
  });
});

describe('AppDetailPage — connectivity warning', () => {
  it('renders the warning message', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        connectivity_warning: {
          target: 'node1',
          service_type: 'mysql',
          message: 'Connectivity check timed out after 30s',
          task_history_id: 555,
        },
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    expect(screen.getByText('Connectivity check timed out after 30s')).toBeInTheDocument();
  });

  it('offers a log affordance and opens the log viewer when task_history_id is present', async () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        connectivity_warning: {
          target: 'node1',
          service_type: 'mysql',
          message: 'Connectivity check timed out after 30s',
          task_history_id: 555,
        },
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    const logButton = screen.getByTestId('connectivity-log-button');
    await userEvent.click(logButton);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/555/)).toBeInTheDocument();
  });

  it('does not offer a log affordance when task_history_id is absent', () => {
    mockUseAppTask.mockReturnValue({
      data: {
        id: 1,
        name: 'FECHK',
        status: 'completed',
        connectivity_warning: {
          target: 'node1',
          service_type: 'mysql',
          message: 'Could not reach the Tasks API',
        },
      },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    expect(screen.getByText('Could not reach the Tasks API')).toBeInTheDocument();
    expect(screen.queryByTestId('connectivity-log-button')).toBeNull();
  });

  it('renders a warning carried via navigation state when the detail query omits it', async () => {
    // detail/list response omits connectivity_warning; carried from create
    // response via router location state.
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });
    const warning = {
      target: 'node1',
      service_type: 'mysql',
      message: 'Connectivity check timed out after 30s',
      task_history_id: 777,
    };

    render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter
            initialEntries={[
              {
                pathname: '/apps/checksums/task/FECHK',
                state: { connectivityWarning: warning },
              },
            ]}
          >
            <Routes>
              <Route
                path="/apps/:plugin/task/:id/*"
                element={<AppDetailPage schema={makeSchema({})} pluginName="checksums" />}
              />
              <Route path="/apps/:plugin" element={<div>list page</div>} />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText('Connectivity check timed out after 30s')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('connectivity-log-button'));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/777/)).toBeInTheDocument();
  });

  it('shows no warning when neither the detail query nor navigation state has one', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderWithSchema(makeSchema({}));

    expect(screen.queryByTestId('connectivity-log-button')).toBeNull();
  });
});
describe('AppDetailPage — schedule summary placement', () => {
  it('renders the ScheduleSummary before the Task information card', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    // `schema` (module-level) has capabilities.scheduling enabled.
    renderAt('/apps/checksums/task/FECHK');

    const summary = screen.getByTestId('schedule-summary');
    const taskInfo = screen.getByText('Task information');

    // DOM order: the schedule summary node comes before the Task information
    // heading, so it is reachable without scrolling past the info card.
    // Bit test (not strict equality) stays correct if a future refactor wraps
    // either node in a container and the browser ORs in containment bits.
    expect(
      summary.compareDocumentPosition(taskInfo) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe('AppDetailPage delete flow', () => {
  it('confirms then calls delete mutation and navigates to list on success', async () => {
    mockDeleteMutate.mockReset();
    mockDeleteMutate.mockResolvedValue(undefined);
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'check1', status: 'completed' },
      isLoading: false,
    });

    renderAt('/apps/checksums/task/check1');

    await userEvent.click(screen.getByTestId('plugin-task-delete'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(mockDeleteMutate).toHaveBeenCalledWith('check1'));
    await waitFor(() => expect(screen.getByText('list page')).toBeInTheDocument());
  });
});

describe('AppDetailPage — write access', () => {
  const taskSchema: AppSchema = {
    pluginName: 'checksums',
    display_name: 'Checksum',
    description: 'Test',
    capabilities: { scheduling: true },
    list_view: {
      columns: [
        { key: 'name', label: 'Name' },
        { key: 'status', label: 'Status', format: 'status' },
      ],
      default_sort: '-id',
    },
    formSchema: { sections: [] },
  } as unknown as AppSchema;

  const entitySchema = {
    pluginName: 'inventory',
    display_name: 'Inventory',
    description: 'Test',
    capabilities: {},
    entities: [
      {
        name: 'services',
        display_name: 'Services',
        forms: [],
        list_view: { columns: [{ key: 'name', label: 'Name' }], default_sort: '-name' },
      },
    ],
    list_view: { columns: [{ key: 'name', label: 'Name' }], default_sort: '-name' },
    formSchema: { sections: [] },
  } as unknown as AppSchema;

  function renderEntityDetail() {
    mockUseAppEntityDetail.mockReturnValue({
      data: { id: 1, name: 'mysql-01' },
      isLoading: false,
      error: null,
    });
    return render(
      <QueryClientProvider client={makeClient()}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/apps/inventory/services/1']}>
            <Routes>
              <Route
                path="/apps/:plugin/:entityName/:id/*"
                element={<AppDetailPage schema={entitySchema} pluginName="inventory" />}
              />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </QueryClientProvider>,
    );
  }

  it('renders execute, edit and delete for a session that may mutate', () => {
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'success', data: { _form: { task_name: 'FECHK' } } },
      isLoading: false,
      error: null,
    });

    renderWithSchema(taskSchema);

    expect(screen.getByTestId('plugin-task-execute')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-task-edit')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-task-delete')).toBeInTheDocument();
  });

  it('renders no execute, edit or delete for a non-admin, keeping the schedule link', () => {
    mockCanMutate = false;
    mockUseAppTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'success', data: { _form: { task_name: 'FECHK' } } },
      isLoading: false,
      error: null,
    });

    renderWithSchema(taskSchema);

    expect(screen.queryByTestId('plugin-task-execute')).not.toBeInTheDocument();
    expect(screen.queryByTestId('plugin-task-edit')).not.toBeInTheDocument();
    expect(screen.queryByTestId('plugin-task-delete')).not.toBeInTheDocument();
    // Navigation-only affordance is untouched.
    expect(screen.getByTestId('plugin-task-schedule')).toBeInTheDocument();
  });

  it('renders entity edit and delete for a session that may mutate', () => {
    renderEntityDetail();

    expect(screen.getByRole('link', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });

  it('renders no entity edit or delete for a non-admin', () => {
    mockCanMutate = false;
    renderEntityDetail();

    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    // The record itself still renders.
    expect(screen.getByText('mysql-01')).toBeInTheDocument();
  });
});
