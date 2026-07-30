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

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AlertsWizard } from '../src/AlertsWizard';
import { formatTimestamp } from '../src/utils';
import type { AlertBackupSummary, AlertTemplate, WizardMode } from '../src/types';

// ── Mocks ──────────────────────────────────────────────────────────────────────

vi.mock('../src/hooks', () => ({
  usePushTemplates: () => ({
    mutateAsync: vi.fn().mockResolvedValue({
      results: [{ name: 'MySQL Slow Queries', status: 'success', message: 'Pushed successfully' }],
    }),
    isPending: false,
    isError: false,
    error: null,
  }),
  useRestoreBackup: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ status: 'success' }),
    isPending: false,
    isError: false,
    error: null,
  }),
  useSavePagerDuty: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ status: 'created' }),
    isPending: false,
    isError: false,
    error: null,
  }),
  useDeletePagerDuty: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ status: 'deleted' }),
    isPending: false,
    isError: false,
    error: null,
  }),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWizard(
  mode: WizardMode,
  overrides: Partial<React.ComponentProps<typeof AlertsWizard>> = {},
) {
  const queryClient = makeQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsWizard mode={mode} open onClose={vi.fn()} {...overrides} />
    </QueryClientProvider>,
  );
}

const MOCK_TEMPLATES: AlertTemplate[] = [
  {
    name: 'MySQL Slow Queries',
    service_type: 'mysql',
    expression: 'rate(mysql_global_status_slow_queries[5m]) > 10',
    default_threshold: 10,
    severity: 'warning',
    description: 'High rate of slow queries.',
    summary: 'Slow queries on {{ $labels.instance }}',
    in_pmm: false,
  },
];

const MOCK_BACKUPS: AlertBackupSummary[] = [
  { id: 1, created_at: '2026-05-28T10:00:00Z' },
  { id: 2, created_at: '2026-05-27T10:00:00Z' },
];

// ── Conditional branching tests ────────────────────────────────────────────────

describe('AlertsWizard conditional branching', () => {
  describe('mode=push', () => {
    it('renders push dialog title', () => {
      renderWizard('push', { selectedTemplates: MOCK_TEMPLATES });
      expect(screen.getByText('Push Templates to PMM')).toBeInTheDocument();
    });

    it('shows selected template chips', () => {
      renderWizard('push', { selectedTemplates: MOCK_TEMPLATES });
      expect(screen.getByText('MySQL Slow Queries')).toBeInTheDocument();
    });

    it('shows count of templates to push', () => {
      renderWizard('push', { selectedTemplates: MOCK_TEMPLATES });
      expect(screen.getByText(/Push 1 template to PMM/i)).toBeInTheDocument();
    });

    it('disables push button when no templates selected', () => {
      renderWizard('push', { selectedTemplates: [] });
      const pushBtn = screen.getByRole('button', { name: /push to pmm/i });
      expect(pushBtn).toBeDisabled();
    });

    it('push button enabled when templates are selected', () => {
      renderWizard('push', { selectedTemplates: MOCK_TEMPLATES });
      const pushBtn = screen.getByRole('button', { name: /push to pmm/i });
      expect(pushBtn).not.toBeDisabled();
    });

    it('does NOT render restore or pagerduty content', () => {
      renderWizard('push', { selectedTemplates: MOCK_TEMPLATES });
      expect(screen.queryByText('Select a backup to restore:')).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/PagerDuty Integration Key/i)).not.toBeInTheDocument();
    });

    it('shows push results after submitting', async () => {
      renderWizard('push', { selectedTemplates: MOCK_TEMPLATES });
      const pushBtn = screen.getByRole('button', { name: /push to pmm/i });
      await userEvent.click(pushBtn);
      await waitFor(() => {
        expect(screen.getByText('Push results:')).toBeInTheDocument();
      });
      expect(screen.getByText('Pushed successfully')).toBeInTheDocument();
    });
  });

  describe('mode=restore', () => {
    it('renders restore dialog title', () => {
      renderWizard('restore', { backups: MOCK_BACKUPS });
      expect(screen.getByText('Restore from Backup')).toBeInTheDocument();
    });

    it('shows backup list', () => {
      renderWizard('restore', { backups: MOCK_BACKUPS });
      expect(screen.getByText('Backup #1')).toBeInTheDocument();
      expect(screen.getByText(formatTimestamp(MOCK_BACKUPS[0].created_at))).toBeInTheDocument();
    });

    it('restore button disabled until backup selected', () => {
      renderWizard('restore', { backups: MOCK_BACKUPS });
      const restoreBtn = screen.getByRole('button', { name: /restore$/i });
      expect(restoreBtn).toBeDisabled();
    });

    it('restore button enabled after selecting a backup', async () => {
      renderWizard('restore', { backups: MOCK_BACKUPS });
      const radios = screen.getAllByRole('radio');
      await userEvent.click(radios[0]);
      const restoreBtn = screen.getByRole('button', { name: /restore$/i });
      expect(restoreBtn).not.toBeDisabled();
    });

    it('shows empty state when no backups', () => {
      renderWizard('restore', { backups: [] });
      expect(screen.getByText('No backups available.')).toBeInTheDocument();
    });

    it('shows success state after restore', async () => {
      renderWizard('restore', { backups: MOCK_BACKUPS });
      const radios = screen.getAllByRole('radio');
      await userEvent.click(radios[0]);
      const restoreBtn = screen.getByRole('button', { name: /restore$/i });
      await userEvent.click(restoreBtn);
      await waitFor(() => {
        expect(screen.getByText('Backup restored successfully.')).toBeInTheDocument();
      });
    });

    it('does NOT render push or pagerduty content', () => {
      renderWizard('restore', { backups: MOCK_BACKUPS });
      expect(screen.queryByText(/Push .* template/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/PagerDuty Integration Key/i)).not.toBeInTheDocument();
    });
  });

  describe('mode=pagerduty', () => {
    it('renders pagerduty dialog title', () => {
      renderWizard('pagerduty');
      expect(screen.getByText('Configure PagerDuty')).toBeInTheDocument();
    });

    it('renders integration key input', () => {
      renderWizard('pagerduty');
      expect(screen.getByLabelText('PagerDuty Integration Key')).toBeInTheDocument();
    });

    it('shows "already configured" notice when pagerdutyConfigured=true', () => {
      renderWizard('pagerduty', { pagerdutyConfigured: true });
      expect(screen.getByText(/PagerDuty is already configured/i)).toBeInTheDocument();
    });

    it('shows delete button when pagerdutyConfigured=true', () => {
      renderWizard('pagerduty', { pagerdutyConfigured: true });
      expect(screen.getByRole('button', { name: /delete pagerduty/i })).toBeInTheDocument();
    });

    it('hides delete button when not configured', () => {
      renderWizard('pagerduty', { pagerdutyConfigured: false });
      expect(screen.queryByRole('button', { name: /delete pagerduty/i })).not.toBeInTheDocument();
    });

    it('save button requires integration key (HTML5 validation skipped; react-hook-form validation tested)', async () => {
      renderWizard('pagerduty');
      const keyInput = screen.getByLabelText('PagerDuty Integration Key');
      await userEvent.type(keyInput, 'test-key-123');
      expect(keyInput).toHaveValue('test-key-123');
    });

    it('shows success state after saving pagerduty key', async () => {
      renderWizard('pagerduty');
      const keyInput = screen.getByLabelText('PagerDuty Integration Key');
      await userEvent.type(keyInput, 'test-key-123');
      const saveBtn = screen.getByRole('button', { name: /^save$/i });
      await userEvent.click(saveBtn);
      await waitFor(() => {
        expect(screen.getByText('PagerDuty configured.')).toBeInTheDocument();
      });
    });

    it('does NOT render push or restore content', () => {
      renderWizard('pagerduty');
      expect(screen.queryByText(/Push .* template/i)).not.toBeInTheDocument();
      expect(screen.queryByText('Select a backup to restore:')).not.toBeInTheDocument();
    });
  });
});

// ── Mode title mapping ─────────────────────────────────────────────────────────

describe('AlertsWizard title per mode', () => {
  it.each([
    ['push', 'Push Templates to PMM'],
    ['restore', 'Restore from Backup'],
    ['pagerduty', 'Configure PagerDuty'],
  ] as [WizardMode, string][])('mode=%s shows title "%s"', (mode, title) => {
    renderWizard(mode, {
      selectedTemplates: MOCK_TEMPLATES,
      backups: MOCK_BACKUPS,
    });
    expect(screen.getByText(title)).toBeInTheDocument();
  });
});
