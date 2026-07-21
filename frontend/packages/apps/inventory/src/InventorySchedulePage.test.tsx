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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

// Hoisted mocks must be set up before imports that use them.
const { apiMock, useAppTasksMock } = vi.hoisted(() => ({
  apiMock: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  useAppTasksMock: vi.fn(),
}));

vi.mock('@sep/api', () => ({
  apiClient: apiMock,
  useAppTasks: (...args: unknown[]) => useAppTasksMock(...args),
}));

import { InventorySchedulePage } from './InventorySchedulePage';
import type { TasksComponents } from '@sep/api';

type PeriodicTaskResponse = TasksComponents['schemas']['PeriodicTaskResponse'];

const TASK_NAME = 'inventory-sync';

const MOCK_SYNCERS = [
  { name: 'myapp.SyncerA', display_name: 'Syncer A' },
  { name: 'myapp.SyncerB', display_name: 'Syncer B' },
];

function makePeriodic(overrides: Partial<PeriodicTaskResponse> = {}): PeriodicTaskResponse {
  return {
    id: 1,
    name: 'periodic-1',
    task: TASK_NAME,
    enabled: true,
    description: '',
    start_time: null,
    last_run_at: null,
    date_changed: null,
    total_run_count: 0,
    interval: { every: 5, period: 'minutes' },
    crontab: null,
    execute_request: null,
    period: 'every 5 minutes',
    next_run_at: null,
    ...overrides,
  };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

function renderPage(schedulingEnabled = true) {
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={['/inventory/schedule']}>
      <QueryClientProvider client={makeClient()}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
  return render(<InventorySchedulePage schedulingEnabled={schedulingEnabled} />, {
    wrapper: Wrapper,
  });
}

function setupHooks(periodic: PeriodicTaskResponse[]) {
  useAppTasksMock.mockReturnValue({
    data: { items: [{ name: TASK_NAME }], pagination: null },
    isLoading: false,
    isError: false,
  });
  apiMock.get.mockImplementation(async (url: string) => {
    if (String(url).includes('/available-syncers/')) {
      return { data: MOCK_SYNCERS };
    }
    // /sep/periodic-tasks/
    return { data: periodic };
  });
}

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.post.mockReset();
  apiMock.put.mockReset();
  apiMock.delete.mockReset();
  useAppTasksMock.mockReset();
});

describe('InventorySchedulePage', () => {
  describe('disabled notice', () => {
    it('shows unavailable alert when schedulingEnabled=false', async () => {
      setupHooks([]);
      renderPage(false);
      await screen.findByTestId('inv-sched-unavailable');
      expect(screen.getByTestId('inv-sched-unavailable')).toHaveTextContent(/SEP_INTERNAL_TOKEN/i);
    });

    it('hides the attach form when schedulingEnabled=false', async () => {
      setupHooks([]);
      renderPage(false);
      await screen.findByTestId('inv-sched-panel');
      expect(screen.queryByTestId('inv-sched-attach')).not.toBeInTheDocument();
    });
  });

  it('loads inventory tasks with fetchAllPages so schedule joins are not capped', async () => {
    setupHooks([]);
    renderPage();
    await screen.findByTestId('inv-sched-panel');
    expect(useAppTasksMock).toHaveBeenCalledWith('inventory', undefined, {
      fetchAllPages: true,
    });
  });

  describe('empty state', () => {
    it('shows empty message when no schedules', async () => {
      setupHooks([]);
      renderPage();
      await screen.findByText(/No inventory-sync schedules configured/i);
    });

    it('shows attach button when schedulingEnabled', async () => {
      setupHooks([]);
      renderPage();
      await screen.findByTestId('inv-sched-attach');
    });
  });

  describe('list view', () => {
    it('renders a row with syncer display_name', async () => {
      setupHooks([
        makePeriodic({
          id: 10,
          execute_request: {
            meta: { syncer: 'myapp.SyncerA' } as unknown as Record<string, never>,
            chain_task_names: [],
            chain_on_failure: false,
          },
        }),
      ]);
      renderPage();
      await screen.findByTestId('inv-sched-row-10');
      expect(screen.getByText('Syncer A')).toBeInTheDocument();
    });

    it('shows "All syncers" when no syncer in meta', async () => {
      setupHooks([makePeriodic({ id: 11, execute_request: null })]);
      renderPage();
      await screen.findByTestId('inv-sched-row-11');
      expect(screen.getByText('All syncers')).toBeInTheDocument();
    });

    it('falls back to raw syncer name when not in available_syncers', async () => {
      setupHooks([
        makePeriodic({
          id: 12,
          execute_request: {
            meta: { syncer: 'unknown.Syncer' } as unknown as Record<string, never>,
            chain_task_names: [],
            chain_on_failure: false,
          },
        }),
      ]);
      renderPage();
      await screen.findByTestId('inv-sched-row-12');
      expect(screen.getByText('unknown.Syncer')).toBeInTheDocument();
    });
  });

  describe('attach form', () => {
    it('lists All syncers and available syncers as radio options', async () => {
      setupHooks([]);
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      const form = await screen.findByTestId('inv-sched-form');
      const group = within(form).getByTestId('inv-sched-syncer-group');

      expect(within(group).getByLabelText('All syncers')).toBeInTheDocument();
      expect(within(group).getByLabelText('Syncer A')).toBeInTheDocument();
      expect(within(group).getByLabelText('Syncer B')).toBeInTheDocument();
    });

    it('interval mode is shown by default', async () => {
      setupHooks([]);
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      await screen.findByTestId('inv-sched-form');
      expect(screen.getByTestId('inv-sched-interval-every')).toBeInTheDocument();
      expect(screen.queryByTestId('inv-sched-cron')).not.toBeInTheDocument();
    });

    it('switching to crontab mode shows cron input and hides interval', async () => {
      setupHooks([]);
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      const form = await screen.findByTestId('inv-sched-form');
      const cronRadio = within(form).getByLabelText('Crontab');
      await user.click(cronRadio);

      expect(screen.getByTestId('inv-sched-cron')).toBeInTheDocument();
      expect(screen.queryByTestId('inv-sched-interval-every')).not.toBeInTheDocument();
    });

    it('submits with meta.syncer for specific syncer selection', async () => {
      setupHooks([]);
      apiMock.post.mockResolvedValue({ data: makePeriodic({ id: 99 }) });
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      const form = await screen.findByTestId('inv-sched-form');

      await user.click(within(form).getByLabelText('Syncer A'));
      await user.click(within(form).getByRole('button', { name: /Attach schedule/i }));

      await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
      const [, body] = apiMock.post.mock.calls[0];
      expect(body.execute_request.meta).toEqual({ syncer: 'myapp.SyncerA' });
    });

    it('submits with empty meta for All syncers selection', async () => {
      setupHooks([]);
      apiMock.post.mockResolvedValue({ data: makePeriodic({ id: 100 }) });
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      // All syncers is selected by default
      await user.click(await screen.findByRole('button', { name: /Attach schedule/i }));

      await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
      const [, body] = apiMock.post.mock.calls[0];
      expect(body.execute_request.meta).toEqual({});
    });

    it('posts to correct task endpoint', async () => {
      setupHooks([]);
      apiMock.post.mockResolvedValue({ data: makePeriodic({ id: 101 }) });
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      await user.click(await screen.findByRole('button', { name: /Attach schedule/i }));

      await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
      const [url] = apiMock.post.mock.calls[0];
      expect(url).toBe(`/sep/periodic-tasks/${TASK_NAME}/`);
    });

    it('shows server error from failed mutation', async () => {
      setupHooks([]);
      apiMock.post.mockRejectedValue(new Error('Unknown syncer'));
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      await user.click(await screen.findByRole('button', { name: /Attach schedule/i }));

      await screen.findByText(/Unknown syncer/i);
    });

    it('rejects invalid cron expression without POST', async () => {
      setupHooks([]);
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      const form = await screen.findByTestId('inv-sched-form');

      await user.click(within(form).getByLabelText('Crontab'));
      await user.type(within(form).getByTestId('inv-sched-cron'), 'not-a-cron');
      await user.click(within(form).getByRole('button', { name: /Attach schedule/i }));

      expect(apiMock.post).not.toHaveBeenCalled();
    });

    it('rejects decimal interval without POST', async () => {
      setupHooks([]);
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-attach'));
      const form = await screen.findByTestId('inv-sched-form');

      const everyInput = within(form).getByTestId('inv-sched-interval-every');
      await user.clear(everyInput);
      await user.type(everyInput, '1.5');
      // fireEvent.submit bypasses HTML5 step-constraint validation so the JS
      // Number.isInteger guard is exercised directly.
      fireEvent.submit(form);

      expect(apiMock.post).not.toHaveBeenCalled();
      expect(await screen.findByRole('alert')).toHaveTextContent(/whole number/i);
    });
  });

  describe('edit form', () => {
    it('does not show syncer radio group in edit mode', async () => {
      setupHooks([makePeriodic({ id: 20 })]);
      apiMock.put.mockResolvedValue({ data: makePeriodic({ id: 20 }) });
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-edit-20'));
      const form = await screen.findByTestId('inv-sched-form');

      expect(within(form).queryByTestId('inv-sched-syncer-group')).not.toBeInTheDocument();
    });

    it('submits updated interval via PUT', async () => {
      setupHooks([makePeriodic({ id: 21 })]);
      apiMock.put.mockResolvedValue({ data: makePeriodic({ id: 21 }) });
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-edit-21'));
      const form = await screen.findByTestId('inv-sched-form');

      const everyInput = within(form).getByTestId('inv-sched-interval-every');
      await user.clear(everyInput);
      await user.type(everyInput, '10');
      await user.click(within(form).getByRole('button', { name: /Save/i }));

      await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
      const [url, body] = apiMock.put.mock.calls[0];
      expect(url).toBe('/sep/periodic-tasks/21');
      expect(body.interval).toMatchObject({ every: 10, period: 'minutes' });
    });
  });

  describe('toggle enabled', () => {
    it('preserves execute_request meta when toggling', async () => {
      setupHooks([
        makePeriodic({
          id: 30,
          enabled: true,
          execute_request: {
            meta: { syncer: 'myapp.SyncerA' } as unknown as Record<string, never>,
            chain_task_names: [],
            chain_on_failure: false,
          },
        }),
      ]);
      apiMock.put.mockResolvedValue({ data: makePeriodic({ id: 30 }) });
      renderPage();

      const toggle = await screen.findByLabelText(/Enable schedule for Syncer A/i);
      await userEvent.click(toggle);

      await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
      const [, body] = apiMock.put.mock.calls[0];
      expect(body.execute_request.meta).toEqual({ syncer: 'myapp.SyncerA' });
      expect(body.enabled).toBe(false);
    });
  });

  describe('clear (delete)', () => {
    it('opens confirmation dialog and fires DELETE on confirm', async () => {
      setupHooks([makePeriodic({ id: 40 })]);
      apiMock.delete.mockResolvedValue({ data: null });
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-delete-40'));
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      await user.click(screen.getByTestId('inv-sched-confirm-delete-40'));
      await waitFor(() => expect(apiMock.delete).toHaveBeenCalledWith('/sep/periodic-tasks/40'));
    });

    it('does NOT fire DELETE when dialog is cancelled', async () => {
      setupHooks([makePeriodic({ id: 41 })]);
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByTestId('inv-sched-delete-41'));
      await user.click(screen.getByRole('button', { name: /^Cancel$/i }));
      expect(apiMock.delete).not.toHaveBeenCalled();
    });
  });
});
