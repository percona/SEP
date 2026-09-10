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
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import { server } from '../../tests/msw-server';
import { AuthProvider, useAuth } from './auth';

const REFRESH_URL = 'http://localhost/api/oauth/refresh';
const SESSION_URL = 'http://localhost/api/oauth/session';
const ME_URL = 'http://localhost/api/users/me';

/** Surface the auth state under test as text nodes. */
function AuthProbe() {
  const { isAuthenticated, ready, user, isAdmin, canMutate } = useAuth();
  return (
    <div>
      <span data-testid="ready">{ready ? 'ready' : 'loading'}</span>
      <span data-testid="authed">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="user">{user?.username ?? 'none'}</span>
      <span data-testid="admin">{isAdmin ? 'yes' : 'no'}</span>
      <span data-testid="can-mutate">{canMutate ? 'yes' : 'no'}</span>
    </div>
  );
}

function renderAuth() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  );
}

describe('AuthProvider bootstrap — ambient Grafana SSO', () => {
  it('auto-logs-in from an ambient session when no SEP refresh cookie exists', async () => {
    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ detail: 'no cookie' }, { status: 401 })),
      http.post(SESSION_URL, () => HttpResponse.json({ access_token: 'ambient', expires_in: 300 })),
      http.get(ME_URL, () => HttpResponse.json({ username: 'alice', isAdmin: false })),
    );

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
    expect(screen.getByTestId('authed')).toHaveTextContent('yes');
    expect(screen.getByTestId('user')).toHaveTextContent('alice');
  });

  it('lands unauthenticated when both refresh and ambient session are rejected', async () => {
    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ detail: 'no cookie' }, { status: 401 })),
      http.post(SESSION_URL, () =>
        HttpResponse.json({ detail: 'no ambient session' }, { status: 401 }),
      ),
    );

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
    expect(screen.getByTestId('authed')).toHaveTextContent('no');
  });

  it('does not attempt ambient session when the SEP refresh succeeds', async () => {
    const sessionCalled = vi.fn();
    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ access_token: 'sep', expires_in: 300 })),
      http.post(SESSION_URL, () => {
        sessionCalled();
        return HttpResponse.json({ access_token: 'ambient', expires_in: 300 });
      }),
      http.get(ME_URL, () => HttpResponse.json({ username: 'bob', isAdmin: false })),
    );

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
    expect(screen.getByTestId('authed')).toHaveTextContent('yes');
    expect(sessionCalled).not.toHaveBeenCalled();
  });
});

describe('useAuth — capability derivation', () => {
  it('resolves to a signed-out, non-admin state outside a provider instead of throwing', () => {
    render(<AuthProbe />);

    expect(screen.getByTestId('ready')).toHaveTextContent('loading');
    expect(screen.getByTestId('authed')).toHaveTextContent('no');
    expect(screen.getByTestId('admin')).toHaveTextContent('no');
    expect(screen.getByTestId('can-mutate')).toHaveTextContent('no');
  });

  it('derives canMutate from the administrator flag for an admin session', async () => {
    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ access_token: 'sep', expires_in: 300 })),
      http.get(ME_URL, () => HttpResponse.json({ username: 'root', isAdmin: true })),
    );

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
    expect(screen.getByTestId('admin')).toHaveTextContent('yes');
    expect(screen.getByTestId('can-mutate')).toHaveTextContent('yes');
  });

  it('withholds canMutate for an authenticated non-admin session', async () => {
    server.use(
      http.post(REFRESH_URL, () => HttpResponse.json({ access_token: 'sep', expires_in: 300 })),
      http.get(ME_URL, () => HttpResponse.json({ username: 'operator', isAdmin: false })),
    );

    renderAuth();

    await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('ready'));
    expect(screen.getByTestId('authed')).toHaveTextContent('yes');
    expect(screen.getByTestId('admin')).toHaveTextContent('no');
    expect(screen.getByTestId('can-mutate')).toHaveTextContent('no');
  });
});
