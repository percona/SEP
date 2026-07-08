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
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { server } from '../../../../tests/msw-server';
import { appsListResponse, makeWrapper, sepListResponse, tasksListResponse } from './fixtures';

const authState = vi.hoisted(() => ({ isAdmin: true }));
vi.mock('../../../contexts/auth', () => ({
  useAuth: () => authState,
}));

import SettingsPage from '../../../pages/SettingsPage';

const SEP_URL = 'http://localhost/api/sep/admin/settings/';
const EXPORT_URL = 'http://localhost/api/sep/admin/settings/export';

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

/** SEP aggregates its local classes and the proxied TasksSettings into one list. */
const combinedListResponse = {
  groups: [...sepListResponse.groups, ...tasksListResponse.groups, ...appsListResponse.groups],
};

function renderPage() {
  return render(<SettingsPage />, { wrapper: makeWrapper() });
}

beforeEach(() => {
  authState.isAdmin = true;
  server.use(
    http.get(SEP_URL, () => HttpResponse.json(combinedListResponse)),
    http.get(EXPORT_URL, () =>
      HttpResponse.text('SEPSettings: {}\n', {
        headers: {
          'Content-Type': 'application/x-yaml',
          'Content-Disposition': 'attachment; filename="sep-config-2026-06-14.yaml"',
        },
      }),
    ),
  );
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('SettingsPage', () => {
  it('shows an Admins-only state for non-admins', () => {
    authState.isAdmin = false;
    renderPage();
    expect(screen.getByTestId('settings-admins-only')).toBeInTheDocument();
    expect(screen.getByText('Admins only')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /download yaml/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /test connection/i })).not.toBeInTheDocument();
  });

  it('shows Download YAML and Test connection for admins', async () => {
    renderPage();
    expect(await screen.findByRole('button', { name: /download yaml/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /test connection/i })).toBeInTheDocument();
  });

  it('requests config export when Download YAML is clicked', async () => {
    let exportCalls = 0;
    server.use(
      http.get(EXPORT_URL, () => {
        exportCalls += 1;
        return HttpResponse.text('SEPSettings: {}\n', {
          headers: {
            'Content-Type': 'application/x-yaml',
            'Content-Disposition': 'attachment; filename="sep-config-2026-06-14.yaml"',
          },
        });
      }),
    );

    const createObjectSpy = vi.fn(() => 'blob:mock-export-url');
    const revokeObjectSpy = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      value: createObjectSpy,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: revokeObjectSpy,
      writable: true,
      configurable: true,
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      renderPage();
      await userEvent.click(await screen.findByRole('button', { name: /download yaml/i }));

      await waitFor(() => {
        expect(exportCalls).toBe(1);
      });
      expect(createObjectSpy).toHaveBeenCalledTimes(1);
      expect(clickSpy).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(URL, 'createObjectURL', {
        value: originalCreateObjectURL,
        writable: true,
        configurable: true,
      });
      Object.defineProperty(URL, 'revokeObjectURL', {
        value: originalRevokeObjectURL,
        writable: true,
        configurable: true,
      });
      clickSpy.mockRestore();
    }
  });

  it('renders one group per class with their settings', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('settings-group-SEPSettings')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('settings-group-SnippetsSettings')).toBeInTheDocument();
    expect(screen.getByTestId('settings-group-TasksSettings')).toBeInTheDocument();
    expect(screen.getByTestId('setting-row-SYNC_REFRESH_TIME')).toBeInTheDocument();
    expect(screen.getByTestId('setting-row-STALENESS_THRESHOLD_SECONDS')).toBeInTheDocument();
  });

  it('filters rows by key substring via the search box', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('setting-row-SYNC_REFRESH_TIME')).toBeInTheDocument(),
    );

    await userEvent.type(screen.getByLabelText('Search settings'), 'STALENESS');

    await waitFor(() =>
      expect(screen.queryByTestId('setting-row-SYNC_REFRESH_TIME')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('setting-row-STALENESS_THRESHOLD_SECONDS')).toBeInTheDocument();
    // The settings search has no debounce (synchronous onChange + pure filter), so
    // fake timers don't apply. Under full-suite parallel load this test can exceed
    // the default 5000ms purely from CPU contention; raise its budget.
  }, 15_000);

  it('hides advanced and non-hot rows by default, revealing advanced on demand', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('setting-row-SYNC_REFRESH_TIME')).toBeInTheDocument(),
    );

    // Advanced hidden by default → FOOTER_TEMPLATE absent.
    expect(screen.queryByTestId('setting-row-FOOTER_TEMPLATE')).not.toBeInTheDocument();
    // Reload defaults to Hot → not_overridable STATIC_DIR absent.
    expect(screen.queryByTestId('setting-row-STATIC_DIR')).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('Filter by advanced'));
    await userEvent.click(await screen.findByRole('option', { name: 'Shown' }));

    expect(await screen.findByTestId('setting-row-FOOTER_TEMPLATE')).toBeInTheDocument();
  });

  it('renders the redacted secret value but never inside the input', async () => {
    renderPage();
    const row = await screen.findByTestId('setting-row-API_SECRET');
    expect(within(row).getByTestId('setting-value-API_SECRET')).toHaveTextContent('**********');
    expect(within(row).getByLabelText('API_SECRET')).toHaveValue('');
  });

  it('renders enabled app-owned groups under the App settings region, labeled by app', async () => {
    renderPage();
    const region = await screen.findByTestId('app-settings-region');
    expect(within(region).getByText('App settings')).toBeInTheDocument();

    // The enabled app's group renders inside the region, tagged with its app.
    const alertsGroup = within(region).getByTestId('settings-group-AlertsSettings');
    expect(alertsGroup).toBeInTheDocument();
    expect(within(region).getByTestId('settings-group-app-label-AlertsSettings')).toHaveTextContent(
      'Alerts',
    );
  });

  it('keeps core groups in the core region, out of the App settings region', async () => {
    renderPage();
    await screen.findByTestId('app-settings-region');

    const region = screen.getByTestId('app-settings-region');
    // Core groups are not tagged and not nested under the App settings region.
    expect(screen.getByTestId('settings-group-SEPSettings')).toBeInTheDocument();
    expect(within(region).queryByTestId('settings-group-SEPSettings')).not.toBeInTheDocument();
    expect(within(region).queryByTestId('settings-group-TasksSettings')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-group-app-label-SEPSettings')).not.toBeInTheDocument();
  });

  it('hides app-owned groups whose owning app is disabled', async () => {
    renderPage();
    await screen.findByTestId('settings-group-SEPSettings');
    // The disabled app's group and its rows never render.
    expect(screen.queryByTestId('settings-group-InventorySettings')).not.toBeInTheDocument();
    expect(screen.queryByTestId('setting-row-INVENTORY_SCAN_INTERVAL')).not.toBeInTheDocument();
  });

  it('keeps disabled apps out of the Class filter dropdown', async () => {
    renderPage();
    await screen.findByTestId('settings-group-SEPSettings');

    await userEvent.click(screen.getByLabelText('Filter by class'));
    const listbox = await screen.findByRole('listbox');
    // Enabled app's class is selectable; disabled app's class never appears.
    expect(within(listbox).getByRole('option', { name: 'AlertsSettings' })).toBeInTheDocument();
    expect(
      within(listbox).queryByRole('option', { name: 'InventorySettings' }),
    ).not.toBeInTheDocument();
  });

  it('omits the App settings region when no enabled app-owned groups remain', async () => {
    server.use(
      http.get(SEP_URL, () =>
        HttpResponse.json({
          groups: [...sepListResponse.groups, appsListResponse.groups[1]],
        }),
      ),
    );
    renderPage();
    await screen.findByTestId('settings-group-SEPSettings');
    expect(screen.queryByTestId('app-settings-region')).not.toBeInTheDocument();
    expect(screen.queryByText('App settings')).not.toBeInTheDocument();
  });

  it('searches across both core and app-owned regions', async () => {
    renderPage();
    await screen.findByTestId('app-settings-region');

    await userEvent.type(screen.getByLabelText('Search settings'), 'ALERTS_RETENTION');

    // App-owned match survives under its region; core rows filter out.
    await waitFor(() =>
      expect(screen.queryByTestId('setting-row-SYNC_REFRESH_TIME')).not.toBeInTheDocument(),
    );
    const region = screen.getByTestId('app-settings-region');
    expect(within(region).getByTestId('setting-row-ALERTS_RETENTION_DAYS')).toBeInTheDocument();
  }, 15_000);
});
