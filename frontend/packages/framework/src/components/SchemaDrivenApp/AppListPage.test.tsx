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

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router';
import { SnackbarProvider } from 'notistack';
import type { AppSchema } from '@sep/api';

// `vi.mock` is hoisted above imports, so the factory must not close over
// module-scope bindings (TDZ risk). Route the useAppTasks mock through a
// `vi.hoisted` spy — the same pattern as ScheduledTasksPanel.test.tsx — so it
// both supplies the rows and captures the options the page passes in.
const { useAppTasksMock, useAppEntityListMock, schemaListViewMock } = vi.hoisted(() => ({
  useAppTasksMock: vi.fn(),
  useAppEntityListMock: vi.fn(),
  schemaListViewMock: vi.fn(),
}));

vi.mock('../SchemaListView', () => ({
  SchemaListView: (props: unknown) => {
    schemaListViewMock(props);
    return <div data-testid="schema-list-view">list</div>;
  },
}));

vi.mock('@sep/api', () => ({
  DEFAULT_APP_LIST_OFFSET: 0,
  DEFAULT_APP_LIST_LIMIT: 50,
  RUNNING_STATUSES: new Set(['running', 'pending']),
  useAppTasks: (...args: unknown[]) => useAppTasksMock(...args),
  useAppEntityList: (...args: unknown[]) => useAppEntityListMock(...args),
  useDeleteAppEntity: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}));

import { AppListPage } from './AppListPage';

const schema: AppSchema = {
  name: 'sched',
  display_name: 'Sched',
  capabilities: { scheduling: true },
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
};

const multiSchema: AppSchema = {
  name: 'inventory',
  display_name: 'Inventory',
  capabilities: { scheduling: false },
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [],
      list_view: { columns: [{ key: 'name', label: 'Name' }] },
    },
    {
      name: 'services',
      display_name: 'Services',
      forms: [],
      list_view: { columns: [{ key: 'name', label: 'Name' }] },
    },
  ],
};

function setTaskRows(rows: Record<string, unknown>[]) {
  useAppTasksMock.mockReturnValue({
    data: { items: rows, pagination: null },
    isLoading: false,
  });
}

function renderPage(props: Partial<Parameters<typeof AppListPage>[0]> = {}) {
  return render(
    <SnackbarProvider>
      <MemoryRouter>
        <AppListPage schema={schema} pluginName="sched" {...props} />
      </MemoryRouter>
    </SnackbarProvider>,
  );
}

beforeEach(() => {
  useAppTasksMock.mockReset();
  useAppEntityListMock.mockReset();
  setTaskRows([]);
  useAppEntityListMock.mockReturnValue({
    data: { items: [], pagination: null },
    isLoading: false,
  });
  schemaListViewMock.mockClear();
});

describe('AppListPage — generic Schedules button', () => {
  it('renders the generic Schedules button by default when scheduling is enabled', () => {
    renderPage();
    expect(screen.getByTestId('plugin-schedule-link')).toBeInTheDocument();
  });

  it('suppresses the generic Schedules button when hideScheduleButton is set', () => {
    renderPage({ hideScheduleButton: true });
    expect(screen.queryByTestId('plugin-schedule-link')).not.toBeInTheDocument();
  });
});

describe('AppListPage — list pagination', () => {
  it('requests the default page from useAppTasks', () => {
    renderPage();

    expect(useAppTasksMock).toHaveBeenCalledWith('sched', undefined, {
      enabled: true,
      disablePolling: false,
      offset: 0,
      limit: 50,
    });
  });

  it('passes server pagination metadata to SchemaListView', () => {
    useAppTasksMock.mockReturnValue({
      data: {
        items: [{ name: 'task-a' }],
        pagination: { total: 120, offset: 0, limit: 50 },
      },
      isLoading: false,
    });

    renderPage();

    expect(schemaListViewMock).toHaveBeenCalledWith(
      expect.objectContaining({
        data: [{ name: 'task-a' }],
        pagination: expect.objectContaining({
          total: 120,
          offset: 0,
          limit: 50,
        }),
      }),
    );
  });

  it('omits server pagination when the hook returns a bare list', () => {
    renderPage();

    expect(schemaListViewMock).toHaveBeenCalledWith(
      expect.objectContaining({
        pagination: null,
      }),
    );
  });

  it('refetches with the new offset when pagination changes', () => {
    useAppTasksMock.mockReturnValue({
      data: {
        items: [{ name: 'task-a' }],
        pagination: { total: 120, offset: 0, limit: 50 },
      },
      isLoading: false,
    });

    renderPage();
    useAppTasksMock.mockClear();

    const pagination = schemaListViewMock.mock.calls.at(-1)?.[0]?.pagination;
    act(() => {
      pagination.onChange({ offset: 50, limit: 50 });
    });

    expect(useAppTasksMock).toHaveBeenCalledWith('sched', undefined, {
      enabled: true,
      disablePolling: false,
      offset: 50,
      limit: 50,
    });
  });

  it('resets offset when the active entity tab changes', async () => {
    useAppEntityListMock.mockReturnValue({
      data: {
        items: [{ id: 1, name: 'node-a' }],
        pagination: { total: 120, offset: 0, limit: 50 },
      },
      isLoading: false,
    });

    const router = createMemoryRouter(
      [
        {
          path: '/inventory/:entityName',
          element: <AppListPage schema={multiSchema} pluginName="inventory" />,
        },
      ],
      { initialEntries: ['/inventory/nodes'] },
    );

    render(
      <SnackbarProvider>
        <RouterProvider router={router} />
      </SnackbarProvider>,
    );

    const pagination = schemaListViewMock.mock.calls.at(-1)?.[0]?.pagination;
    act(() => {
      pagination.onChange({ offset: 50, limit: 50 });
    });

    expect(useAppEntityListMock).toHaveBeenCalledWith('inventory', 'nodes', undefined, {
      enabled: true,
      offset: 50,
      limit: 50,
    });

    useAppEntityListMock.mockClear();

    await act(async () => {
      await router.navigate('/inventory/services');
    });

    expect(useAppEntityListMock).toHaveBeenCalledWith('inventory', 'services', undefined, {
      enabled: true,
      offset: 0,
      limit: 50,
    });
    expect(useAppEntityListMock).not.toHaveBeenCalledWith(
      'inventory',
      'services',
      undefined,
      expect.objectContaining({ offset: 50 }),
    );
  });
});

describe('AppListPage — server-side query', () => {
  const serverSchema: AppSchema = {
    name: 'inventory',
    display_name: 'Inventory',
    entities: [
      {
        name: 'nodes',
        display_name: 'Nodes',
        forms: [],
        list_view: {
          columns: [{ key: 'name', label: 'Name', sortable: true }],
          default_sort: '-created_at',
          server_side_query: true,
        },
      },
    ],
  };

  function renderServerPage() {
    const router = createMemoryRouter(
      [
        {
          path: '/inventory/:entityName',
          element: <AppListPage schema={serverSchema} pluginName="inventory" />,
        },
      ],
      { initialEntries: ['/inventory/nodes'] },
    );
    return render(
      <SnackbarProvider>
        <RouterProvider router={router} />
      </SnackbarProvider>,
    );
  }

  beforeEach(() => {
    useAppEntityListMock.mockReturnValue({
      data: {
        items: [{ id: 1, name: 'node-a' }],
        pagination: { total: 120, offset: 0, limit: 50 },
      },
      isLoading: false,
    });
  });

  it('seeds the list query with the schema default_sort when capability is on', () => {
    renderServerPage();

    expect(useAppEntityListMock).toHaveBeenCalledWith('inventory', 'nodes', undefined, {
      enabled: true,
      offset: 0,
      limit: 50,
      sort: '-created_at',
      search: undefined,
    });
    expect(schemaListViewMock).toHaveBeenCalledWith(
      expect.objectContaining({
        serverQuery: expect.objectContaining({
          sort: '-created_at',
        }),
      }),
    );
  });

  it('refetches from offset 0 when sort changes', () => {
    renderServerPage();

    const pagination = schemaListViewMock.mock.calls.at(-1)?.[0]?.pagination;
    act(() => {
      pagination.onChange({ offset: 50, limit: 50 });
    });
    useAppEntityListMock.mockClear();

    const serverQuery = schemaListViewMock.mock.calls.at(-1)?.[0]?.serverQuery;
    act(() => {
      serverQuery.onSortChange('name');
    });

    expect(useAppEntityListMock).toHaveBeenCalledWith('inventory', 'nodes', undefined, {
      enabled: true,
      offset: 0,
      limit: 50,
      sort: 'name',
      search: undefined,
    });
  });

  it('refetches from offset 0 when search changes', () => {
    renderServerPage();

    const pagination = schemaListViewMock.mock.calls.at(-1)?.[0]?.pagination;
    act(() => {
      pagination.onChange({ offset: 50, limit: 50 });
    });
    useAppEntityListMock.mockClear();

    const serverQuery = schemaListViewMock.mock.calls.at(-1)?.[0]?.serverQuery;
    act(() => {
      serverQuery.onSearchChange('db1');
    });

    expect(useAppEntityListMock).toHaveBeenCalledWith('inventory', 'nodes', undefined, {
      enabled: true,
      offset: 0,
      limit: 50,
      sort: '-created_at',
      search: 'db1',
    });
  });

  it('does not pass serverQuery when the capability is off', () => {
    renderPage();

    expect(schemaListViewMock).toHaveBeenCalledWith(
      expect.objectContaining({
        serverQuery: null,
      }),
    );
  });
});

describe('AppListPage — "Currently running" affordance', () => {
  it('shows the count of running/pending tasks when at least one is running', () => {
    setTaskRows([
      { name: 'a', status: 'running' },
      { name: 'b', status: 'success' },
      { name: 'c', status: 'pending' },
    ]);
    renderPage();
    expect(screen.getByTestId('currently-running')).toHaveTextContent('Currently running (2)');
  });

  it('renders no affordance when nothing is running', () => {
    setTaskRows([
      { name: 'a', status: 'success' },
      { name: 'b', status: 'failed' },
    ]);
    renderPage();
    expect(screen.queryByTestId('currently-running')).not.toBeInTheDocument();
  });

  it('renders no affordance for an empty list', () => {
    setTaskRows([]);
    renderPage();
    expect(screen.queryByTestId('currently-running')).not.toBeInTheDocument();
  });
});

describe('AppListPage — poll-while-running escape hatch', () => {
  it('leaves task-list polling enabled by default', () => {
    renderPage();
    expect(useAppTasksMock).toHaveBeenCalledWith(
      'sched',
      undefined,
      expect.objectContaining({ disablePolling: false }),
    );
  });

  it('forwards disableTaskPolling to useAppTasks so tests/stories issue no repeats', () => {
    renderPage({ disableTaskPolling: true });
    expect(useAppTasksMock).toHaveBeenCalledWith(
      'sched',
      undefined,
      expect.objectContaining({ disablePolling: true }),
    );
  });
});
