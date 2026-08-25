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

import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { ApiError, apiClient } from '@sep/api';
import { TargetHostsPage } from './TargetHostsPage';

const HOSTS = [
  { id: 'nomad-1', name: 'db-mysql-prod-01', address: '10.0.0.1' },
  { id: 'nomad-2', name: 'db-mysql-prod-02', address: '10.0.0.2' },
];

function renderPage(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/inventory/target-hosts']}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TargetHostsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders Name and Address columns with host rows', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: HOSTS } as never);

    renderPage(<TargetHostsPage />);

    expect(await screen.findByText('db-mysql-prod-01')).toBeInTheDocument();
    expect(screen.getByText('db-mysql-prod-02')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.2')).toBeInTheDocument();
    // Column headers.
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Address')).toBeInTheDocument();
  });

  it('stays client-side: no server search box without pagination or capability', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: HOSTS } as never);

    renderPage(<TargetHostsPage />);

    await screen.findByText('db-mysql-prod-01');
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it('shows a loading indicator while the hosts query is in flight', () => {
    // Never-resolving promise keeps the query pending so `isLoading` stays true.
    vi.spyOn(apiClient, 'get').mockReturnValue(new Promise(() => {}) as never);

    renderPage(<TargetHostsPage />);

    // MRT renders linear progress in its toolbars while `state.isLoading`.
    expect(screen.getAllByRole('progressbar').length).toBeGreaterThan(0);
  });

  it('surfaces an error state when the hosts query fails (proxy 502)', async () => {
    vi.spyOn(apiClient, 'get').mockRejectedValue(
      new ApiError({ kind: 'http', status: 502, message: 'tasks unreachable' }),
    );

    renderPage(<TargetHostsPage />);

    const alert = await screen.findByTestId('target-hosts-error');
    expect(alert).toHaveTextContent('Failed to load target hosts');
    expect(alert).toHaveTextContent('tasks unreachable');
  });

  it('renders an empty table when no hosts are available', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] } as never);

    renderPage(<TargetHostsPage />);

    expect(await screen.findByText('No records to display')).toBeInTheDocument();
  });
});
