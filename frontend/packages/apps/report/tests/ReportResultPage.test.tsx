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

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import type { ReactNode } from 'react';
import { ReportResultPage } from '../src/ReportResultPage';
import type { ReportData } from '../src/types';

vi.mock('@sep/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import { apiClient } from '@sep/api';
const mockedApi = apiClient as unknown as {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
};

const MOCK_REPORT: ReportData = {
  full: true,
  refresh: false,
  metadata: {
    title: 'Health & Security Report',
    generated_at: '2026-05-28T10:00:00Z',
    report_week: 'Report 2026 Week 22',
    report_interval: 'May 21 – May 28, 2026',
  },
  monitored: { total_nodes: 3, total_services: 5, services_by_type: { mysql: 3, mongodb: 2 } },
  advisors: {
    total_checks: 10,
    total_failed: 1,
    refresh_issues: [],
    families: [
      {
        family_key: 'FAMILY_MYSQL',
        display_name: 'MySQL',
        checks: [],
        failed: {
          MySQLCheck: [
            {
              name: 'MySQLCheck',
              description: 'Check MySQL config',
              summary: 'MySQL config issue',
              severity: 'SEVERITY_WARNING',
              service_name: 'mysql-prod',
              read_more_url: '',
            },
          ],
        },
      },
    ],
  },
  alerts: {
    total_alerts: 2,
    alerts_per_service: {},
    alerts_per_rule: {},
    alerts_per_host: {},
    alerts_daily: {},
  },
  backups: {
    total_backups: 4,
    backups_by_host: {},
    backups_by_status: {},
    backups_by_type: {},
    failed_backups: [
      {
        id: 'b1',
        alias: 'daily',
        name: 'node-1',
        type: 'physical',
        status: 'fail',
        size: '0',
        estimated_data: false,
        encryption: 'None',
        period: {},
      },
    ],
    all_backups: [],
  },
  storage: { entries: [] },
  uptime: { entries: [] },
  inventory: { entries: [] },
};

function renderWithProviders(ui: ReactNode, locationState?: unknown) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const initialEntries = locationState
    ? [{ pathname: '/result', state: locationState }]
    : ['/result'];
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/result" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReportResultPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('shows warning when no params in navigation state', () => {
    renderWithProviders(<ReportResultPage />);
    expect(screen.getByText(/no report parameters/i)).toBeInTheDocument();
  });

  it('renders report data after successful fetch', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('/apps/report/config')) {
        return Promise.resolve({ data: { upload_disabled_reasons: [] } });
      }
      return Promise.resolve({ data: MOCK_REPORT });
    });

    renderWithProviders(<ReportResultPage />, {
      params: { since: 'now-7d', until: 'now', full: true, refresh: false },
    });

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /health.*security report/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/3 nodes/i)).toBeInTheDocument();
    expect(screen.getByText(/5 services/i)).toBeInTheDocument();
    expect(screen.getByText(/1 advisor failure/i)).toBeInTheDocument();
    expect(screen.getByText(/MySQL config issue/i)).toBeInTheDocument();
    expect(screen.getByText(/node-1/)).toBeInTheDocument();
  });

  it('starts a PDF job and downloads with the server filename', async () => {
    const originalCreateElement = document.createElement.bind(document);
    const anchor = originalCreateElement('a');
    vi.spyOn(anchor, 'click').mockImplementation(() => undefined);
    vi.spyOn(document, 'createElement').mockImplementation((tagName, options) =>
      tagName === 'a' ? anchor : originalCreateElement(tagName, options),
    );
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('/apps/report/config')) {
        return Promise.resolve({ data: { upload_disabled_reasons: [] } });
      }
      if (url.endsWith('/apps/report/pdf-jobs/job-1/pdf')) {
        return Promise.resolve({
          data: new Blob(['%PDF'], { type: 'application/pdf' }),
          headers: {
            'content-disposition':
              'attachment; filename="Health_and_Security_Report_2026-05-28.pdf"',
          },
        });
      }
      if (url.endsWith('/apps/report/pdf-jobs/job-1')) {
        return Promise.resolve({
          data: {
            job_id: 'job-1',
            status: 'success',
            pdf_ready: true,
            result: { filename: 'Health_and_Security_Report_2026-05-28.pdf' },
          },
        });
      }
      return Promise.resolve({ data: MOCK_REPORT });
    });
    mockedApi.post.mockResolvedValue({
      data: { job_id: 'job-1', status: 'pending', pdf_ready: false },
    });

    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fake-url'),
      revokeObjectURL: vi.fn(),
    });

    renderWithProviders(<ReportResultPage />, {
      params: { since: 'now-7d', until: 'now', full: true, refresh: false },
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download pdf/i })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('button', { name: /download pdf/i }));

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith('/apps/report/pdf-jobs', {
        report: MOCK_REPORT,
      });
    });
    await waitFor(() => {
      expect(anchor.download).toBe('Health_and_Security_Report_2026-05-28.pdf');
    });
  });

  it('keeps polling retry state without a local timeout', async () => {
    const jobStates = [
      { job_id: 'job-1', status: 'retry', pdf_ready: false },
      { job_id: 'job-1', status: 'success', pdf_ready: true },
    ];
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('/apps/report/config')) {
        return Promise.resolve({ data: { upload_disabled_reasons: [] } });
      }
      if (url.endsWith('/apps/report/pdf-jobs/job-1/pdf')) {
        return Promise.resolve({ data: new Blob(['%PDF'], { type: 'application/pdf' }) });
      }
      if (url.endsWith('/apps/report/pdf-jobs/job-1')) {
        return Promise.resolve({ data: jobStates.shift() });
      }
      return Promise.resolve({ data: MOCK_REPORT });
    });
    mockedApi.post.mockResolvedValue({
      data: { job_id: 'job-1', status: 'pending', pdf_ready: false },
    });

    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fake-url'),
      revokeObjectURL: vi.fn(),
    });

    renderWithProviders(<ReportResultPage />, {
      params: { since: 'now-7d', until: 'now', full: true, refresh: false },
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download pdf/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /download pdf/i }));

    await waitFor(
      () => {
        expect(mockedApi.get).toHaveBeenCalledWith('/apps/report/pdf-jobs/job-1/pdf', {
          responseType: 'blob',
        });
      },
      { timeout: 2_500 },
    );
  });

  it('reports revoked PDF jobs as terminal failures', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('/apps/report/config')) {
        return Promise.resolve({ data: { upload_disabled_reasons: [] } });
      }
      if (url.endsWith('/apps/report/pdf-jobs/job-1')) {
        return Promise.resolve({
          data: { job_id: 'job-1', status: 'revoked', pdf_ready: false, error: 'Report disabled' },
        });
      }
      return Promise.resolve({ data: MOCK_REPORT });
    });
    mockedApi.post.mockResolvedValue({
      data: { job_id: 'job-1', status: 'pending', pdf_ready: false },
    });

    renderWithProviders(<ReportResultPage />, {
      params: { since: 'now-7d', until: 'now', full: true, refresh: false },
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /download pdf/i })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('button', { name: /download pdf/i }));

    await waitFor(() => {
      expect(screen.getByText(/pdf download failed: report disabled/i)).toBeInTheDocument();
    });
    expect(mockedApi.get).not.toHaveBeenCalledWith('/apps/report/pdf-jobs/job-1/pdf', {
      responseType: 'blob',
    });
  });

  it('starts an upload job on upload button click', async () => {
    let uploadStarted = false;
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('/apps/report/config')) {
        return Promise.resolve({ data: { upload_disabled_reasons: [] } });
      }
      if (uploadStarted) {
        return Promise.resolve({
          data: {
            job_id: 'job-2',
            status: 'success',
            pdf_ready: false,
            result: { sys_id: 'abc123', status: 'uploaded' },
          },
        });
      }
      return Promise.resolve({ data: MOCK_REPORT });
    });
    mockedApi.post.mockImplementation(() => {
      uploadStarted = true;
      return Promise.resolve({ data: { job_id: 'job-2', status: 'pending', pdf_ready: false } });
    });

    renderWithProviders(<ReportResultPage />, {
      params: { since: 'now-7d', until: 'now', full: true, refresh: false },
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /upload to servicenow/i })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('button', { name: /upload to servicenow/i }));

    await waitFor(() => {
      expect(mockedApi.post).toHaveBeenCalledWith('/apps/report/upload-jobs', {
        report: MOCK_REPORT,
      });
    });
  });

  it('disables upload button when upload_disabled_reasons returned', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('/apps/report/config')) {
        return Promise.resolve({
          data: { upload_disabled_reasons: ['ServiceNow credentials not configured'] },
        });
      }
      return Promise.resolve({ data: MOCK_REPORT });
    });

    renderWithProviders(<ReportResultPage />, {
      params: { since: 'now-7d', until: 'now', full: true, refresh: false },
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /upload to servicenow/i })).toBeDisabled();
    });
  });
});
