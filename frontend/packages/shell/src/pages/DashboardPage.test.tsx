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

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../contexts/auth', () => ({
  useAuth: () => ({ user: { username: 'dba' } }),
}));

vi.mock('@sep/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/api')>()),
  useDashboardStats: () => ({
    data: { nodes: 1, tasks: 2, snippets: 3, targets: 4 },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

const mockUseTaskHistory = vi.fn();

vi.mock('@sep/framework', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/framework')>()),
  useTaskHistory: (...args: unknown[]) => mockUseTaskHistory(...args),
}));

import DashboardPage from './DashboardPage';

const EMPTY_HISTORY = {
  data: { items: [] },
  isLoading: false,
  isError: false,
  error: null,
};

function makeItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    display_name: 'run-python',
    task: { name: 'run-python', owner: 'ANY' },
    execution_request: { target: 'db1', task: 'run-python', payload: null, meta: {} },
    status: 'success',
    started_at: '2026-01-01T00:00:00Z',
    has_logs: false,
    ...overrides,
  };
}

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: '/', element: <DashboardPage /> },
      { path: '*', element: <div data-testid="navigated-away" /> },
    ],
    { initialEntries: ['/'] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(() => {
  mockUseTaskHistory.mockReturnValue(EMPTY_HISTORY);
});

describe('DashboardPage', () => {
  it.each([
    ['stat-nodes', 'Nodes', '1'],
    ['stat-targets', 'Targets', '4'],
  ])('renders the %s count without linking anywhere', async (testId, label, value) => {
    const router = renderDashboard();
    const startingPath = router.state.location.pathname;

    const card = await screen.findByTestId(testId);
    expect(card).toHaveTextContent(label);
    expect(card).toHaveTextContent(value);

    fireEvent.click(card);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(startingPath);
    });
  });

  it('requests task history with excludeInternal and limit 5', () => {
    renderDashboard();
    expect(mockUseTaskHistory).toHaveBeenCalledWith({ limit: 5, excludeInternal: true });
  });

  it('renders display_name as the task name button', async () => {
    mockUseTaskHistory.mockReturnValue({
      ...EMPTY_HISTORY,
      data: { items: [makeItem({ display_name: 'my_snippet.py' })] },
    });
    renderDashboard();
    expect(await screen.findByRole('button', { name: 'my_snippet.py' })).toBeInTheDocument();
  });

  it('derives task link from owner BACKUP_MONGO', async () => {
    mockUseTaskHistory.mockReturnValue({
      ...EMPTY_HISTORY,
      data: {
        items: [
          makeItem({
            display_name: 'my-backup',
            task: { name: 'backup-task', owner: 'BACKUP_MONGO' },
          }),
        ],
      },
    });
    renderDashboard();
    const btn = await screen.findByRole('button', { name: 'my-backup' });
    expect(btn).toHaveAttribute(
      'data-task-link',
      `/backups/mongodb/backups/task/${encodeURIComponent('backup-task')}`,
    );
  });

  it('derives task link from owner ALTERS', async () => {
    mockUseTaskHistory.mockReturnValue({
      ...EMPTY_HISTORY,
      data: {
        items: [makeItem({ task: { name: 'pt-osc', owner: 'ALTERS' } })],
      },
    });
    renderDashboard();
    const btn = await screen.findByRole('button', { name: 'run-python' });
    expect(btn).toHaveAttribute(
      'data-task-link',
      `/schema-change/alters/task/${encodeURIComponent('pt-osc')}`,
    );
  });

  it('falls back to /tasks/<name> for unknown owner via ANY', async () => {
    mockUseTaskHistory.mockReturnValue({
      ...EMPTY_HISTORY,
      data: {
        items: [makeItem({ task: { name: 'some-task', owner: 'UNKNOWN_OWNER' } })],
      },
    });
    renderDashboard();
    const btn = await screen.findByRole('button', { name: 'run-python' });
    expect(btn).toHaveAttribute('data-task-link', `/tasks/${encodeURIComponent('some-task')}`);
  });

  it('routes RESTORES owner to /tasks/:taskName', async () => {
    mockUseTaskHistory.mockReturnValue({
      ...EMPTY_HISTORY,
      data: {
        items: [makeItem({ task: { name: 'restore-task', owner: 'RESTORES' } })],
      },
    });
    renderDashboard();
    const btn = await screen.findByRole('button', { name: 'run-python' });
    expect(btn).toHaveAttribute('data-task-link', `/tasks/${encodeURIComponent('restore-task')}`);
  });

  it('navigates to the task link when the task name button is clicked', async () => {
    mockUseTaskHistory.mockReturnValue({
      ...EMPTY_HISTORY,
      data: {
        items: [
          makeItem({
            display_name: 'my-alter',
            task: { name: 'my-alter', owner: 'ALTERS' },
          }),
        ],
      },
    });
    const router = renderDashboard();

    const btn = await screen.findByRole('button', { name: 'my-alter' });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/schema-change/alters/task/my-alter');
    });
  });
});
