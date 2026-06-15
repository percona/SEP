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
import { makeWrapper, sepListResponse, tasksListResponse } from './fixtures';

const authState = vi.hoisted(() => ({ isAdmin: true }));
vi.mock('../../../contexts/auth', () => ({
  useAuth: () => authState,
}));

import SettingsPage from '../../../pages/SettingsPage';

const SEP_URL = 'http://localhost/api/sep/admin/settings/';

/** SEP aggregates its local classes and the proxied TasksSettings into one list. */
const combinedListResponse = {
  groups: [...sepListResponse.groups, ...tasksListResponse.groups],
};

function renderPage() {
  return render(<SettingsPage />, { wrapper: makeWrapper() });
}

beforeEach(() => {
  authState.isAdmin = true;
  server.use(http.get(SEP_URL, () => HttpResponse.json(combinedListResponse)));
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
  });

  it('renders the redacted secret value but never inside the input', async () => {
    renderPage();
    const row = await screen.findByTestId('setting-row-API_SECRET');
    expect(within(row).getByTestId('setting-value-API_SECRET')).toHaveTextContent('**********');
    expect(within(row).getByLabelText('API_SECRET')).toHaveValue('');
  });
});
