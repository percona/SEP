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

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AdminApp } from '@sep/api';

import { server } from '../../../tests/msw-server';
import { NotificationProvider } from '../../contexts/notification';

const authState = vi.hoisted(() => ({ isAdmin: true }));
vi.mock('../../contexts/auth', () => ({
  useAuth: () => authState,
}));

import AdminAppsPage from '../AdminAppsPage';

const LIST_URL = 'http://localhost/api/admin/apps/';
const stateUrl = (key: string) => `http://localhost/api/admin/apps/${key}/state`;
const forceDisableUrl = (key: string) => `http://localhost/api/admin/apps/${key}/force-disable`;

/** Build an AdminApp with sensible defaults overridable per field. */
function makeApp(overrides: Partial<AdminApp> = {}): AdminApp {
  return {
    app_key: 'snippets',
    name: 'Snippets',
    enabled: true,
    lifecycle_state: 'ENABLED',
    toggleable: true,
    uri_path: '/snippets',
    css_class: 'snippets',
    sidebar: true,
    has_api_router: true,
    ...overrides,
  };
}

/** Register a GET handler that serves the current `apps` snapshot. */
function serveList(apps: AdminApp[]) {
  server.use(http.get(LIST_URL, () => HttpResponse.json(apps)));
}

let queryClient: QueryClient;

function makeWrapper() {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <NotificationProvider>{children}</NotificationProvider>
      </QueryClientProvider>
    );
  };
}

function renderPage() {
  return render(<AdminAppsPage />, { wrapper: makeWrapper() });
}

beforeEach(() => {
  authState.isAdmin = true;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('AdminAppsPage', () => {
  it('shows an Admins-only state for non-admins and fetches nothing', () => {
    authState.isAdmin = false;
    let listCalls = 0;
    server.use(
      http.get(LIST_URL, () => {
        listCalls += 1;
        return HttpResponse.json([]);
      }),
    );

    renderPage();

    expect(screen.getByTestId('admin-apps-admins-only')).toBeInTheDocument();
    expect(screen.getByText('Admins only')).toBeInTheDocument();
    expect(listCalls).toBe(0);
  });

  it('lists each app with its name and lifecycle state', async () => {
    serveList([
      makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' }),
      makeApp({
        app_key: 'messages',
        name: 'Messages',
        enabled: false,
        lifecycle_state: 'DISABLED',
      }),
    ]);

    renderPage();

    expect(await screen.findByText('Snippets')).toBeInTheDocument();
    expect(screen.getByTestId('app-state-snippets')).toHaveTextContent('Enabled');
    expect(screen.getByText('Messages')).toBeInTheDocument();
    expect(screen.getByTestId('app-state-messages')).toHaveTextContent('Disabled');
  });

  it('enables a disabled app by sending lifecycle_state=ENABLING', async () => {
    serveList([
      makeApp({
        app_key: 'messages',
        name: 'Messages',
        enabled: false,
        lifecycle_state: 'DISABLED',
      }),
    ]);
    let body: unknown;
    server.use(
      http.put(stateUrl('messages'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          app_key: 'messages',
          enabled: false,
          lifecycle_state: 'ENABLING',
        });
      }),
    );

    renderPage();
    const row = await screen.findByTestId('app-row-messages');
    await userEvent.click(within(row).getByRole('switch'));

    await waitFor(() => expect(body).toEqual({ lifecycle_state: 'ENABLING' }));
  });

  it('disables an enabled app by sending lifecycle_state=DISABLING', async () => {
    serveList([makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' })]);
    let body: unknown;
    server.use(
      http.put(stateUrl('snippets'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          app_key: 'snippets',
          enabled: true,
          lifecycle_state: 'DISABLING',
        });
      }),
    );

    renderPage();
    const row = await screen.findByTestId('app-row-snippets');
    await userEvent.click(within(row).getByRole('switch'));

    await waitFor(() => expect(body).toEqual({ lifecycle_state: 'DISABLING' }));
  });

  it('renders a transitional app as locked and in-progress', async () => {
    serveList([
      makeApp({
        app_key: 'snippets',
        name: 'Snippets',
        lifecycle_state: 'ENABLING',
        enabled: false,
      }),
    ]);

    renderPage();
    const row = await screen.findByTestId('app-row-snippets');

    expect(within(row).getByTestId('app-state-snippets')).toHaveTextContent('Enabling');
    expect(within(row).getByRole('switch')).toBeDisabled();
    expect(within(row).getByLabelText('transition in progress')).toBeInTheDocument();
  });

  it('renders a protected app as locked with no toggle', async () => {
    serveList([
      makeApp({
        app_key: 'inventory',
        name: 'Inventory',
        toggleable: false,
        lifecycle_state: 'ENABLED',
      }),
    ]);

    renderPage();
    const row = await screen.findByTestId('app-row-inventory');

    expect(within(row).getByTestId('app-protected-inventory')).toBeInTheDocument();
    expect(within(row).queryByRole('switch')).not.toBeInTheDocument();
  });

  it('offers Force disable only while DISABLING and calls the endpoint', async () => {
    serveList([
      makeApp({
        app_key: 'snippets',
        name: 'Snippets',
        enabled: false,
        lifecycle_state: 'DISABLING',
      }),
    ]);
    let forceCalls = 0;
    server.use(
      http.post(forceDisableUrl('snippets'), () => {
        forceCalls += 1;
        return HttpResponse.json({
          app_key: 'snippets',
          enabled: false,
          lifecycle_state: 'DISABLED',
        });
      }),
    );

    renderPage();
    const button = await screen.findByTestId('app-force-disable-snippets');
    await userEvent.click(button);

    await waitFor(() => expect(forceCalls).toBe(1));
  });

  it('does not offer Force disable for a non-DISABLING app', async () => {
    serveList([makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' })]);

    renderPage();
    await screen.findByTestId('app-row-snippets');

    expect(screen.queryByTestId('app-force-disable-snippets')).not.toBeInTheDocument();
  });

  it('surfaces a readable error when a transition is rejected (409)', async () => {
    serveList([makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' })]);
    server.use(
      http.put(stateUrl('snippets'), () =>
        HttpResponse.json(
          { detail: "App 'snippets' cannot move from ENABLED to DISABLING." },
          { status: 409 },
        ),
      ),
    );

    renderPage();
    const row = await screen.findByTestId('app-row-snippets');
    await userEvent.click(within(row).getByRole('switch'));

    expect(
      await screen.findByText("App 'snippets' cannot move from ENABLED to DISABLING."),
    ).toBeInTheDocument();
  });

  it('invalidates the admin and public apps queries on a successful transition', async () => {
    serveList([makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' })]);
    server.use(
      http.put(stateUrl('snippets'), () =>
        HttpResponse.json({ app_key: 'snippets', enabled: true, lifecycle_state: 'DISABLING' }),
      ),
    );

    renderPage();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const row = await screen.findByTestId('app-row-snippets');
    await userEvent.click(within(row).getByRole('switch'));

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['admin', 'apps'] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['apps'] });
    });
  });

  it("locks the row's switch while its transition is in flight", async () => {
    serveList([makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' })]);
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.put(stateUrl('snippets'), async () => {
        await gate;
        return HttpResponse.json({
          app_key: 'snippets',
          enabled: true,
          lifecycle_state: 'DISABLING',
        });
      }),
    );

    renderPage();
    const row = await screen.findByTestId('app-row-snippets');
    await userEvent.click(within(row).getByRole('switch'));

    await waitFor(() => expect(within(row).getByRole('switch')).toBeDisabled());
    release();
  });

  it('reflects the new lifecycle state on the chip after a transition', async () => {
    const apps = [makeApp({ app_key: 'snippets', name: 'Snippets', lifecycle_state: 'ENABLED' })];
    server.use(
      http.get(LIST_URL, () => HttpResponse.json(apps)),
      http.put(stateUrl('snippets'), () => {
        apps[0] = { ...apps[0], enabled: true, lifecycle_state: 'DISABLING' };
        return HttpResponse.json({
          app_key: 'snippets',
          enabled: true,
          lifecycle_state: 'DISABLING',
        });
      }),
    );

    renderPage();
    const row = await screen.findByTestId('app-row-snippets');
    await userEvent.click(within(row).getByRole('switch'));

    expect(await within(row).findByText('Disabling…')).toBeInTheDocument();
  });
});
