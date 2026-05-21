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
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import type { PluginSchema } from '@sep/api';
import { PluginDetailPage, pickExecutionData, resolveTabFromSplat } from './PluginDetailPage';

const mockDeleteMutate = vi.fn();
const mockExecuteMutate = vi.fn();
const mockUsePluginTask = vi.fn();

// Manual factory keeps axios out of the resolution graph.
vi.mock('@sep/api', () => ({
  usePluginTask: (...args: unknown[]) => mockUsePluginTask(...args),
  useDeletePluginTask: () => ({
    mutateAsync: mockDeleteMutate,
    isPending: false,
  }),
  useDeletePluginEntity: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePluginEntityDetail: () => ({ data: undefined, isLoading: false, error: null }),
  // Needed by useTaskLogs / useExecutionEvents in the component tree
  getToken: () => null,
  refreshAccessToken: vi.fn(),
  emitUnauthorized: vi.fn(),
  apiClient: { get: vi.fn(), post: vi.fn(), defaults: {} },
  setTokenProvider: vi.fn(),
}));

vi.mock('../../hooks', () => ({
  useTaskHistoryByName: () => ({ data: { items: [] }, isLoading: false, error: null }),
  useExecuteTask: () => ({
    mutateAsync: mockExecuteMutate,
    isPending: false,
  }),
}));

const schema: PluginSchema = {
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
} as unknown as PluginSchema;

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
              path="/plugins/:plugin/task/:id/*"
              element={<PluginDetailPage schema={schema} pluginName="checksums" />}
            />
            <Route path="/plugins/:plugin" element={<div>list page</div>} />
          </Routes>
        </MemoryRouter>
      </SnackbarProvider>
    </QueryClientProvider>,
  );
}

describe('pickExecutionData', () => {
  it('returns null when no data field', () => {
    expect(pickExecutionData({})).toBeNull();
    expect(pickExecutionData({ data: null })).toBeNull();
    expect(pickExecutionData({ data: 'string' })).toBeNull();
  });

  it('returns null when data has no command/args/target', () => {
    expect(pickExecutionData({ data: {} })).toBeNull();
    expect(pickExecutionData({ data: { meta: {} } })).toBeNull();
    expect(pickExecutionData({ data: { foo: 'bar' } })).toBeNull();
  });

  it('reads from data.meta first', () => {
    const result = pickExecutionData({
      data: { meta: { command: 'pt-table-checksum', target: 'pmm' } },
    });
    expect(result).toEqual({ command: 'pt-table-checksum', args: undefined, target: 'pmm' });
  });

  it('falls back to data.* when meta is missing', () => {
    const result = pickExecutionData({
      data: { command: 'legacy-cmd', args: '--foo', target: 'host' },
    });
    expect(result).toEqual({ command: 'legacy-cmd', args: '--foo', target: 'host' });
  });

  it('prefers meta over data.* when both present', () => {
    const result = pickExecutionData({
      data: { command: 'old', meta: { command: 'new' } },
    });
    expect(result?.command).toBe('new');
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

describe('PluginDetailPage execute flow', () => {
  it('confirms then calls execute mutation on success', async () => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockResolvedValue({ id: 99 });
    mockUsePluginTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/plugins/checksums/task/FECHK');

    await userEvent.click(screen.getByTestId('plugin-task-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() => expect(mockExecuteMutate).toHaveBeenCalledWith({ taskName: 'FECHK' }));
  });

  it('shows error snackbar and closes dialog on execute failure', async () => {
    mockExecuteMutate.mockReset();
    mockExecuteMutate.mockRejectedValue(new Error('Execute failed'));
    mockUsePluginTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/plugins/checksums/task/FECHK');

    await userEvent.click(screen.getByTestId('plugin-task-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByTestId('plugin-task-execute-confirm'));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('Execute failed')).toBeInTheDocument());
  });

  it('closes dialog without calling execute when cancelled', async () => {
    mockExecuteMutate.mockReset();
    mockUsePluginTask.mockReturnValue({
      data: { id: 1, name: 'FECHK', status: 'completed' },
      isLoading: false,
    });

    renderAt('/plugins/checksums/task/FECHK');

    await userEvent.click(screen.getByTestId('plugin-task-execute'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mockExecuteMutate).not.toHaveBeenCalled();
  });
});

describe('PluginDetailPage delete flow', () => {
  it('confirms then calls delete mutation and navigates to list on success', async () => {
    mockDeleteMutate.mockReset();
    mockDeleteMutate.mockResolvedValue(undefined);
    mockUsePluginTask.mockReturnValue({
      data: { id: 1, name: 'check1', status: 'completed' },
      isLoading: false,
    });

    renderAt('/plugins/checksums/task/check1');

    await userEvent.click(screen.getByTestId('plugin-task-delete'));

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(mockDeleteMutate).toHaveBeenCalledWith('check1'));
    await waitFor(() => expect(screen.getByText('list page')).toBeInTheDocument());
  });
});
