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
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type * as ReactRouterDom from 'react-router-dom';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ReactNode } from 'react';
import { ReportFormPage } from '../src/ReportFormPage';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactRouterDom>();
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderWithProviders(ui: ReactNode, initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="*" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReportFormPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders heading and generate button', () => {
    renderWithProviders(<ReportFormPage />);
    expect(screen.getByRole('heading', { name: /health.*security report/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate report/i })).toBeInTheDocument();
  });

  it('renders period selects with defaults', () => {
    renderWithProviders(<ReportFormPage />);
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/to/i)).toBeInTheDocument();
  });

  it('renders full-report and cached-advisor radio options', () => {
    renderWithProviders(<ReportFormPage />);
    expect(screen.getByLabelText(/full report/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/summary only/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/use cached advisor/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/refresh advisor/i)).toBeInTheDocument();
  });

  it('navigates to result with default params on submit', async () => {
    renderWithProviders(<ReportFormPage />);
    await userEvent.click(screen.getByRole('button', { name: /generate report/i }));
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        'result',
        expect.objectContaining({
          state: {
            params: expect.objectContaining({
              since: 'now-7d',
              until: 'now',
              full: true,
              refresh: false,
            }),
          },
        }),
      );
    });
  });
});
