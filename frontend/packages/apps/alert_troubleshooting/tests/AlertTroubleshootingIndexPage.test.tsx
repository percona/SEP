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

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import type { ReactNode } from 'react';
import { AlertTroubleshootingIndexPage } from '../src/AlertTroubleshootingIndexPage';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn() },
}));

import { apiClient } from '@sep/api';
const mockedApi = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

function renderWithProviders(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AlertTroubleshootingIndexPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders service type accordion sections', async () => {
    mockedApi.get.mockResolvedValue({
      data: [
        {
          service_type: 'mysql',
          label: 'MySQL',
          alerts: [{ name: 'MySQLSlowQueries', label: 'MySQL Slow Queries' }],
        },
        {
          service_type: 'mongodb',
          label: 'MongoDB',
          alerts: [{ name: 'MongoDBReplicaLag', label: 'MongoDB Replica Lag' }],
        },
      ],
    });

    renderWithProviders(<AlertTroubleshootingIndexPage />);

    await waitFor(() => {
      expect(screen.getAllByText(/MySQL/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/MongoDB/i).length).toBeGreaterThan(0);
    });
  });

  it('renders alert links inside accordion', async () => {
    mockedApi.get.mockResolvedValue({
      data: [
        {
          service_type: 'mysql',
          label: 'MySQL',
          alerts: [{ name: 'MySQLSlowQueries', label: 'MySQL Slow Queries' }],
        },
      ],
    });

    renderWithProviders(<AlertTroubleshootingIndexPage />);

    await waitFor(() => {
      expect(screen.getByText('MySQL Slow Queries')).toBeInTheDocument();
    });
  });

  it('renders empty state when no groups returned', async () => {
    mockedApi.get.mockResolvedValue({ data: [] });

    renderWithProviders(<AlertTroubleshootingIndexPage />);

    await waitFor(() => {
      expect(screen.getByText(/no alerts found/i)).toBeInTheDocument();
    });
  });
});
