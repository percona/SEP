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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type * as FrameworkModule from '@sep/framework';

const { useScheduledTasksForAppMock } = vi.hoisted(() => ({
  useScheduledTasksForAppMock: vi.fn(),
}));

// Mock only the schedule hook; pull the real period/time helpers from the
// framework so recurrence/next-run wording stays accurate and stays in sync
// with the scheduled-tasks table and detail summary.
vi.mock('@sep/framework', async (importOriginal) => {
  const actual = await importOriginal<typeof FrameworkModule>();
  return {
    ...actual,
    useScheduledTasksForApp: (...args: unknown[]) => useScheduledTasksForAppMock(...args),
  };
});

import { InventoryScheduleSummary } from './InventoryScheduleSummary';
import type { PeriodicTaskResponse } from '@sep/framework';

const NOW = new Date('2026-06-18T12:00:00Z');

function makePeriodic(overrides: Partial<PeriodicTaskResponse> = {}): PeriodicTaskResponse {
  return {
    id: 1,
    name: 'periodic-1',
    task: 'inventory.sync',
    enabled: true,
    description: '',
    start_time: null,
    last_run_at: null,
    date_changed: null,
    total_run_count: 0,
    interval: { every: 2, period: 'hours' },
    crontab: null,
    execute_request: null,
    period: 'every 2 hours',
    next_run_at: '2026-06-18T14:00:00Z',
    ...overrides,
  };
}

function setup(
  periodicTasks: PeriodicTaskResponse[],
  extra: { isLoading?: boolean; isError?: boolean } = {},
) {
  useScheduledTasksForAppMock.mockReturnValue({
    periodicTasks,
    isLoading: extra.isLoading ?? false,
    isError: extra.isError ?? false,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  useScheduledTasksForAppMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('InventoryScheduleSummary', () => {
  it('makes the empty state explicit when no schedules are configured', () => {
    setup([]);
    render(<InventoryScheduleSummary schedulingEnabled disablePolling />);

    expect(screen.getByTestId('inv-schedule-summary-empty')).toHaveTextContent(
      'No inventory-sync schedules configured',
    );
    expect(screen.queryByTestId('inv-schedule-summary-scheduled')).not.toBeInTheDocument();
  });

  it('shows recurrence and next run when a schedule is configured', () => {
    setup([makePeriodic()]);
    render(<InventoryScheduleSummary schedulingEnabled disablePolling />);

    const scheduled = screen.getByTestId('inv-schedule-summary-scheduled');
    expect(scheduled).toHaveTextContent('Sync scheduled');
    expect(scheduled).toHaveTextContent('every 2 hours');
    expect(scheduled).toHaveTextContent('next run in 2 hours');
    expect(scheduled).not.toHaveTextContent('more');
  });

  it('surfaces the soonest schedule and counts the rest when several exist', () => {
    setup([
      makePeriodic({
        id: 1,
        next_run_at: '2026-06-18T20:00:00Z',
        interval: { every: 1, period: 'days' },
        period: 'every 1 days',
      }),
      makePeriodic({
        id: 2,
        next_run_at: '2026-06-18T13:00:00Z',
        interval: { every: 1, period: 'hours' },
        period: 'every 1 hours',
      }),
    ]);
    render(<InventoryScheduleSummary schedulingEnabled disablePolling />);

    const scheduled = screen.getByTestId('inv-schedule-summary-scheduled');
    expect(scheduled).toHaveTextContent('every 1 hours');
    expect(scheduled).toHaveTextContent('next run in 1 hour');
    expect(scheduled).toHaveTextContent('(+1 more)');
  });

  it('omits the next-run clause for a configured-but-not-upcoming schedule', () => {
    setup([makePeriodic({ next_run_at: null })]);
    render(<InventoryScheduleSummary schedulingEnabled disablePolling />);

    const scheduled = screen.getByTestId('inv-schedule-summary-scheduled');
    expect(scheduled).toHaveTextContent('every 2 hours');
    expect(scheduled).not.toHaveTextContent('next run');
  });

  it('shows a loading state while schedules are being fetched', () => {
    setup([], { isLoading: true });
    render(<InventoryScheduleSummary schedulingEnabled disablePolling />);

    expect(screen.getByTestId('inv-schedule-summary')).toHaveTextContent('Checking schedules…');
    expect(screen.queryByTestId('inv-schedule-summary-empty')).not.toBeInTheDocument();
  });

  it('does not claim "no schedules" when the lookup fails', () => {
    setup([], { isError: true });
    render(<InventoryScheduleSummary schedulingEnabled disablePolling />);

    expect(screen.getByTestId('inv-schedule-summary-error')).toHaveTextContent(
      'Schedule status unavailable',
    );
    expect(screen.queryByTestId('inv-schedule-summary-empty')).not.toBeInTheDocument();
  });

  it('renders nothing when scheduling is unavailable', () => {
    setup([]);
    const { container } = render(
      <InventoryScheduleSummary schedulingEnabled={false} disablePolling />,
    );

    expect(screen.queryByTestId('inv-schedule-summary')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
