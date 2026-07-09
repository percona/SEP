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
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { server } from '../tests/msw-server';
import Providers from './Providers';
import AuthGuard from './components/AuthGuard';
import { NavigationProvider } from './contexts/navigation';

const REFRESH_URL = 'http://localhost/api/oauth/refresh';
const SESSION_URL = 'http://localhost/api/oauth/session';
const ME_URL = 'http://localhost/api/users/me';
const APPS_URL = 'http://localhost/api/apps/';

/** Let any in-flight fetch reach its MSW handler before asserting. */
const flushPendingRequests = () => new Promise((resolve) => setTimeout(resolve, 0));

// The authenticated shell (its header and sidebar) is the only consumer of the
// navigation context, so the navigation provider lives inside the guarded shell
// — not above the route guard where it would fetch during bootstrap.
function renderApp() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/']}>
        <Providers>
          <Routes>
            <Route path="/login" element={<div>login screen</div>} />
            <Route
              path="/"
              element={
                <AuthGuard>
                  <NavigationProvider>
                    <div>authenticated shell</div>
                  </NavigationProvider>
                </AuthGuard>
              }
            />
          </Routes>
        </Providers>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  // NavigationProvider seeds `sidebarOpen` from matchMedia, absent under jsdom.
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('authenticated provider boundary — no eager request during ambient bootstrap', () => {
  it('withholds the navigation-metadata request while ambient sign-in is pending, then fetches once the shell mounts', async () => {
    const appsSpy = vi.fn();
    let releaseSession: () => void = () => {};
    const ambientPending = new Promise<void>((resolve) => {
      releaseSession = resolve;
    });

    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ detail: 'no cookie' }, { status: 401 })),
      http.post(SESSION_URL, async () => {
        await ambientPending;
        return HttpResponse.json({ access_token: 'ambient', expires_in: 300 });
      }),
      http.get(ME_URL, () => HttpResponse.json({ username: 'alice', isAdmin: false })),
      http.get(APPS_URL, () => {
        appsSpy();
        return HttpResponse.json([]);
      }),
    );

    renderApp();

    // Ambient sign-in is still in flight: the guard shows its spinner, and no
    // authenticated request has escaped above the guard to trigger a redirect.
    await screen.findByRole('progressbar');
    await flushPendingRequests();
    expect(appsSpy).not.toHaveBeenCalled();
    expect(screen.queryByText('login screen')).toBeNull();

    // Ambient sign-in completes: the shell mounts and only now fetches nav metadata.
    releaseSession();
    await screen.findByText('authenticated shell');
    expect(appsSpy).toHaveBeenCalled();
    expect(screen.queryByText('login screen')).toBeNull();
  });

  it('falls back to the login screen without fetching navigation metadata when no session resolves', async () => {
    const appsSpy = vi.fn();

    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ detail: 'no cookie' }, { status: 401 })),
      http.post(SESSION_URL, () =>
        HttpResponse.json({ detail: 'no ambient session' }, { status: 401 }),
      ),
      http.get(APPS_URL, () => {
        appsSpy();
        return HttpResponse.json([]);
      }),
    );

    renderApp();

    await screen.findByText('login screen');
    expect(appsSpy).not.toHaveBeenCalled();
    expect(screen.queryByText('authenticated shell')).toBeNull();
  });
});
