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

import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppSchema } from '@sep/api';
import { TasksApp } from './TasksApp';
import { useTasksList, useTasksAppSchema } from './hooks';

vi.mock('./hooks', () => ({
  useTasksAppSchema: vi.fn(),
  useTasksList: vi.fn(),
  useTaskDetail: vi.fn(),
}));

vi.mock('./TaskDetailPage', () => ({
  TaskDetailPage: () => <div data-testid="task-detail-page">Task detail</div>,
}));

vi.mock('@sep/framework', () => ({
  SchemaListView: ({ data }: { data: Record<string, unknown>[] }) => (
    <div data-testid="schema-list">
      {data.map((row) => (
        <span key={String(row.name)}>{String(row.name)}</span>
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
    columns: [{ key: 'name', label: 'Name', sortable: true }],
    default_sort: 'name',
  },
};

function renderApp(initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <TasksApp />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TasksApp', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTasksAppSchema.mockReturnValue({
      data: mockSchema,
      isLoading: false,
      error: null,
    } as ReturnType<typeof useTasksAppSchema>);
    mockUseTasksList.mockReturnValue({
      data: { items: [], pagination: null },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useTasksList>);
  });

  it('renders the list page at the index route', () => {
    renderApp('/');

    expect(screen.getByRole('heading', { name: 'Task Manager' })).toBeInTheDocument();
    expect(screen.getByTestId('schema-list')).toBeInTheDocument();
  });

  it('renders the detail page for a task route', () => {
    renderApp('/my-task');

    expect(screen.getByTestId('task-detail-page')).toBeInTheDocument();
  });
});
