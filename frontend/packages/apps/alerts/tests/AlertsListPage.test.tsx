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
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertsListPage } from '../src/AlertsListPage';
import type { AlertIndexResponse } from '../src/types';

/** Flipped per test to cover the read-only (non-admin) rendering. */
let mockCanMutate = true;

vi.mock('@sep/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/api')>()),
  useAuth: () => ({ isAdmin: mockCanMutate, canMutate: mockCanMutate }),
}));

const index: AlertIndexResponse = {
  pmm_connected: true,
  pagerduty: null,
  recent_backups: [{ id: 1, created_at: '2026-07-22T10:00:00Z' }],
  groups: [
    {
      service_type: 'mysql',
      label: 'MySQL',
      templates: [
        {
          name: 'MySQL Slow Queries',
          service_type: 'mysql',
          expression: 'rate(x[5m]) > 1',
          default_threshold: 1,
          severity: 'warning',
          description: 'Slow queries are piling up',
          summary: 'Slow queries',
          in_pmm: false,
        },
      ],
    },
  ],
};

vi.mock('../src/hooks', () => ({
  useAlertsIndex: () => ({ data: index, isLoading: false, error: null }),
  useAlertBackups: () => ({ data: undefined }),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AlertsListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockCanMutate = true;
});

describe('AlertsListPage — write access', () => {
  it('renders push, restore, PagerDuty and template selection for a session that may mutate', () => {
    renderPage();

    expect(screen.getByRole('button', { name: /Push Selected/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Restore from Backup/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Configure PagerDuty/i })).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: /Select all MySQL templates/i }),
    ).toBeInTheDocument();
  });

  it('renders none of those controls for a non-admin', () => {
    mockCanMutate = false;
    renderPage();

    expect(screen.queryByRole('button', { name: /Push Selected/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Restore from Backup/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Configure PagerDuty/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('checkbox', { name: /Select all MySQL templates/i }),
    ).not.toBeInTheDocument();
    // The templates themselves stay readable.
    expect(screen.getByText('MySQL Slow Queries')).toBeInTheDocument();
  });
});
