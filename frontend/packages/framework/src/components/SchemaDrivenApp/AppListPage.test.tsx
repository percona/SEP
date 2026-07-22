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
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import type { AppSchema } from '@sep/api';

// `vi.mock` is hoisted above imports, so the factory must not close over
// module-scope bindings (TDZ risk). Route the useAppTasks mock through a
// `vi.hoisted` spy — the same pattern as ScheduledTasksPanel.test.tsx — so it
// both supplies the rows and captures the options the page passes in.
const { useAppTasksMock } = vi.hoisted(() => ({ useAppTasksMock: vi.fn() }));

vi.mock('../SchemaListView', () => ({
  SchemaListView: () => <div>list</div>,
}));

vi.mock('@sep/api', () => ({
  RUNNING_STATUSES: new Set(['running', 'pending']),
  useAppTasks: (...args: unknown[]) => useAppTasksMock(...args),
  useAppEntityList: () => ({ data: [], isLoading: false }),
  useDeleteAppEntity: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}));

import { AppListPage } from './AppListPage';

const schema: AppSchema = {
  name: 'sched',
  display_name: 'Sched',
  capabilities: { scheduling: true },
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
};

function setTaskRows(rows: Record<string, unknown>[]) {
  useAppTasksMock.mockReturnValue({ data: rows, isLoading: false });
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
  setTaskRows([]);
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
