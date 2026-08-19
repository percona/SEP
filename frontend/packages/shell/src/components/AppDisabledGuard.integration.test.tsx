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

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { EnabledApp } from '@sep/api';

import { server } from '../../tests/msw-server';
import AppDisabledGuard from './AppDisabledGuard';

// Exercises the real `useEnabledApps` hook (no vi.mock) end to end: the query
// fetches `GET /api/apps/` over MSW, the `blocking_dependencies` field
// deserializes onto `EnabledApp`, and the guard maps it to the named splash.
// The colocated AppDisabledGuard.test.tsx mocks the hook to drive lifecycle
// states; this pins the network contract those unit tests stub out.

const APPS_URL = 'http://localhost/api/apps/';

const app = (overrides: Partial<EnabledApp>): EnabledApp => ({
  app_key: 'snippets',
  enabled: true,
  sidebar: true,
  uri_path: '/snippets',
  display_name: 'Snippet Manager',
  custom_ui: false,
  group: null,
  nav_order: null,
  react_route: '/snippets',
  nav_icon: null,
  blocking_dependencies: [],
  ...overrides,
});

function serveApps(apps: EnabledApp[]) {
  server.use(http.get(APPS_URL, () => HttpResponse.json(apps)));
}

function renderGuard(appKey: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AppDisabledGuard appKey={appKey}>
          <div data-testid="child">child route</div>
        </AppDisabledGuard>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AppDisabledGuard + useEnabledApps (network contract)', () => {
  it('names the blocking dependency deserialized from the live response', async () => {
    serveApps([
      app({
        app_key: 'atw',
        display_name: 'Support diagnostics',
        enabled: false,
        blocking_dependencies: ['snippets'],
      }),
      app({ app_key: 'snippets', display_name: 'Snippet Manager', enabled: false }),
    ]);
    renderGuard('atw');

    await waitFor(() =>
      expect(screen.getByText('Support diagnostics is unavailable')).toBeInTheDocument(),
    );
    expect(
      screen.getByText(
        'The Snippet Manager app must be enabled first. Contact an administrator to enable it.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('child')).not.toBeInTheDocument();
  });

  it('renders the wrapped route when the live response reports the app enabled', async () => {
    serveApps([app({ app_key: 'atw', display_name: 'Support diagnostics', enabled: true })]);
    renderGuard('atw');

    await waitFor(() => expect(screen.getByTestId('child')).toBeInTheDocument());
  });
});
