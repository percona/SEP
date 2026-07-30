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
import { MemoryRouter, Route, Routes } from 'react-router';
import type { ReactNode } from 'react';
import { AlertTroubleshootingDetailPage } from '../src/AlertTroubleshootingDetailPage';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn() },
}));

vi.mock('@sep/framework', () => ({
  SnippetExecutionAccordion: ({
    snippetFilename,
    title,
  }: {
    snippetFilename: string;
    title?: string;
  }) => (
    <div data-testid="snippet-accordion" data-filename={snippetFilename}>
      {title ?? snippetFilename}
    </div>
  ),
  StandaloneHostSelector: ({ onChange }: { value: string; onChange: (id: string) => void }) => (
    <button data-testid="host-selector" onClick={() => onChange('db1')}>
      Executor Host
    </button>
  ),
}));

import { apiClient } from '@sep/api';
const mockedApi = apiClient as unknown as { get: ReturnType<typeof vi.fn> };

function renderAtRoute(path: string, ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/:serviceType/:alertName" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AlertTroubleshootingDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders host selector and one accordion per snippet', async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        alert: { name: 'MySQLSlowQueries', label: 'MySQL Slow Queries', service_type: 'mysql' },
        snippets: [
          {
            filename: 'check_slow.sh',
            title: 'Check Slow Queries',
            description: null,
            is_approved: true,
          },
          {
            filename: 'check_locks.sh',
            title: 'Check Locks',
            description: null,
            is_approved: true,
          },
        ],
      },
    });

    renderAtRoute('/mysql/MySQLSlowQueries', <AlertTroubleshootingDetailPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('snippet-accordion')).toHaveLength(2);
    });

    expect(screen.getByTestId('host-selector')).toBeInTheDocument();
  });

  it('renders StandaloneHostSelector for page-level host selection', async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        alert: { name: 'MySQLSlowQueries', label: 'MySQL Slow Queries', service_type: 'mysql' },
        snippets: [{ filename: 'check.sh', title: 'Check', description: null, is_approved: true }],
      },
    });

    renderAtRoute('/mysql/MySQLSlowQueries', <AlertTroubleshootingDetailPage />);

    await waitFor(() => expect(screen.getByTestId('host-selector')).toBeInTheDocument());
  });

  it('renders empty state when no snippets', async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        alert: { name: 'EmptyAlert', label: 'Empty Alert', service_type: 'mysql' },
        snippets: [],
      },
    });

    renderAtRoute('/mysql/EmptyAlert', <AlertTroubleshootingDetailPage />);

    await waitFor(() => {
      expect(screen.getByText(/no diagnostic snippets/i)).toBeInTheDocument();
    });
  });

  it('renders alert label as page heading', async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        alert: { name: 'MySQLSlowQueries', label: 'MySQL Slow Queries', service_type: 'mysql' },
        snippets: [{ filename: 'check.sh', title: 'Check', description: null, is_approved: true }],
      },
    });

    renderAtRoute('/mysql/MySQLSlowQueries', <AlertTroubleshootingDetailPage />);

    await waitFor(() => {
      expect(screen.getByText('MySQL Slow Queries')).toBeInTheDocument();
    });
  });

  it('renders warning alert for unapproved snippets instead of accordion', async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        alert: { name: 'MySQLSlowQueries', label: 'MySQL Slow Queries', service_type: 'mysql' },
        snippets: [
          {
            filename: 'check_slow.sh',
            title: 'Check Slow Queries',
            description: null,
            is_approved: false,
          },
        ],
      },
    });

    renderAtRoute('/mysql/MySQLSlowQueries', <AlertTroubleshootingDetailPage />);

    await waitFor(() => {
      expect(screen.getByText(/Check Slow Queries is not approved/i)).toBeInTheDocument();
    });

    expect(screen.queryByTestId('snippet-accordion')).not.toBeInTheDocument();
  });

  it('renders accordion for approved snippets but warning for unapproved ones', async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        alert: { name: 'MySQLSlowQueries', label: 'MySQL Slow Queries', service_type: 'mysql' },
        snippets: [
          {
            filename: 'check_slow.sh',
            title: 'Check Slow Queries',
            description: null,
            is_approved: true,
          },
          {
            filename: 'debug_locks.sh',
            title: 'Debug Locks',
            description: null,
            is_approved: false,
          },
        ],
      },
    });

    renderAtRoute('/mysql/MySQLSlowQueries', <AlertTroubleshootingDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId('snippet-accordion')).toBeInTheDocument();
    });

    expect(screen.getByText(/Debug Locks is not approved/i)).toBeInTheDocument();
    expect(screen.queryByTestId('snippet-accordion')).toHaveAttribute(
      'data-filename',
      'check_slow.sh',
    );
  });
});
