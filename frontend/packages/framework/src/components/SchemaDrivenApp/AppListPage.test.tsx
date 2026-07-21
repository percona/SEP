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
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import type { AppSchema } from '@sep/api';
import { AppListPage } from './AppListPage';

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
  useAppTasks: (...args: unknown[]) => useAppTasksMock(...args),
  useAppEntityList: (...args: unknown[]) => useAppEntityListMock(...args),
  useDeleteAppEntity: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}));

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
  useAppTasksMock.mockReturnValue({
    data: { items: [], pagination: null },
    isLoading: false,
  });
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
      offset: 50,
      limit: 50,
    });
  });

  it('resets offset when the active entity tab changes', () => {
    useAppEntityListMock.mockReturnValue({
      data: {
        items: [{ id: 1, name: 'node-a' }],
        pagination: { total: 120, offset: 50, limit: 50 },
      },
      isLoading: false,
    });

    render(
      <SnackbarProvider>
        <MemoryRouter initialEntries={['/inventory/nodes']}>
          <Routes>
            <Route
              path="/inventory/:entityName"
              element={<AppListPage schema={multiSchema} pluginName="inventory" />}
            />
          </Routes>
        </MemoryRouter>
      </SnackbarProvider>,
    );

    const pagination = schemaListViewMock.mock.calls.at(-1)?.[0]?.pagination;
    pagination.onChange({ offset: 50, limit: 50 });
    useAppEntityListMock.mockClear();

    render(
      <SnackbarProvider>
        <MemoryRouter initialEntries={['/inventory/services']}>
          <Routes>
            <Route
              path="/inventory/:entityName"
              element={<AppListPage schema={multiSchema} pluginName="inventory" />}
            />
          </Routes>
        </MemoryRouter>
      </SnackbarProvider>,
    );

    expect(useAppEntityListMock).toHaveBeenCalledWith('inventory', 'services', undefined, {
      enabled: true,
      offset: 0,
      limit: 50,
    });
  });
});
