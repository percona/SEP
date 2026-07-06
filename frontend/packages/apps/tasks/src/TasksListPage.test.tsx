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
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppSchema } from '@sep/api';
import { TasksListPage } from './TasksListPage';
import { useTasksList, useTasksAppSchema } from './hooks';

const navigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('./hooks', () => ({
  useTasksAppSchema: vi.fn(),
  useTasksList: vi.fn(),
}));

vi.mock('@sep/framework', () => ({
  SchemaListView: ({
    data,
    onRowClick,
  }: {
    data: Record<string, unknown>[];
    onRowClick?: (row: Record<string, unknown>) => void;
  }) => (
    <div data-testid="schema-list">
      {data.map((row) => (
        <button key={String(row.name)} type="button" onClick={() => onRowClick?.(row)}>
          {String(row.name)}
        </button>
      ))}
    </div>
  ),
}));

const mockUseTasksAppSchema = vi.mocked(useTasksAppSchema);
const mockUseTasksList = vi.mocked(useTasksList);

const mockSchema: AppSchema = {
  name: 'tasks',
  display_name: 'Task Manager',
  description: 'View task definitions and execution history.',
  forms: [],
  list_view: {
    columns: [
      { key: 'name', label: 'Name', sortable: true },
      { key: 'backend', label: 'Backend', sortable: true },
    ],
    default_sort: 'name',
  },
};

describe('TasksListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTasksAppSchema.mockReturnValue({
      data: mockSchema,
      isLoading: false,
      error: null,
    } as ReturnType<typeof useTasksAppSchema>);
    mockUseTasksList.mockReturnValue({
      data: [
        {
          name: 'monitor-task',
          backend: 'nomad',
          created_at: '2026-05-19T12:00:00Z',
          created_by: null,
          last_updated_by: null,
        },
      ],
      isLoading: false,
      error: null,
    } as ReturnType<typeof useTasksList>);
  });

  it('renders the schema title and description', () => {
    render(
      <MemoryRouter>
        <TasksListPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Task Manager' })).toBeInTheDocument();
    expect(screen.getByText(/view task definitions and execution history/i)).toBeInTheDocument();
  });

  it('renders task rows from the list hook', () => {
    render(
      <MemoryRouter>
        <TasksListPage />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('schema-list')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'monitor-task' })).toBeInTheDocument();
  });

  it('navigates to the task detail route when a row is clicked', () => {
    render(
      <MemoryRouter>
        <TasksListPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'monitor-task' }));

    expect(navigate).toHaveBeenCalledWith('monitor-task');
  });

  it('shows a loading indicator while the schema is loading', () => {
    mockUseTasksAppSchema.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useTasksAppSchema>);

    render(
      <MemoryRouter>
        <TasksListPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('shows an error when the schema fails to load', () => {
    mockUseTasksAppSchema.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('schema unavailable'),
    } as ReturnType<typeof useTasksAppSchema>);

    render(
      <MemoryRouter>
        <TasksListPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('schema unavailable');
  });

  it('shows an error when the task list fails to load', () => {
    mockUseTasksList.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('list unavailable'),
    } as ReturnType<typeof useTasksList>);

    render(
      <MemoryRouter>
        <TasksListPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('list unavailable');
  });
});
