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
import { delay, http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ConnectivityResult, ConnectivityStatus } from '@sep/api';

import { server } from '../../../../tests/msw-server';
import { makeWrapper } from './fixtures';
import TestConnectionButton from '../TestConnectionButton';

const CONN_URL = 'http://localhost/api/sep/admin/connectivity-check/';

function renderButton() {
  return render(<TestConnectionButton />, { wrapper: makeWrapper() });
}

/** Register a one-shot success handler returning the given results. */
function stubResults(results: ConnectivityResult[]) {
  server.use(http.post(CONN_URL, () => HttpResponse.json(results)));
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('TestConnectionButton', () => {
  it('is idle by default: enabled button, no results, no error', () => {
    renderButton();
    const button = screen.getByRole('button', { name: /test connection/i });
    expect(button).toBeEnabled();
    expect(screen.queryByTestId('connectivity-results')).not.toBeInTheDocument();
    expect(screen.queryByTestId('connectivity-error')).not.toBeInTheDocument();
  });

  it('shows a pending state while the request is in flight', async () => {
    server.use(
      http.post(CONN_URL, async () => {
        await delay(50);
        return HttpResponse.json([
          { service: 'pmm', reachable: true, status: 'reachable', detail: 'OK' },
        ] satisfies ConnectivityResult[]);
      }),
    );

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    // Disabled + relabelled while pending.
    await waitFor(() => expect(screen.getByRole('button', { name: /testing/i })).toBeDisabled());
    // Recovers once resolved.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /test connection/i })).toBeEnabled(),
    );
  });

  it('renders one independent row per service with status chip and detail', async () => {
    stubResults([
      { service: 'pmm', reachable: true, status: 'reachable', detail: 'PMM OK', version: '2.44.0' },
      { service: 'inventory', reachable: false, status: 'auth_failed', detail: 'Invalid API key' },
      { service: 'tasks', reachable: false, status: 'timeout', detail: 'Timed out after 5s' },
      { service: 'nomad', reachable: false, status: 'unreachable', detail: 'Connection refused' },
    ]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    const results = await screen.findByTestId('connectivity-results');
    // All four rows present — one unreachable service does not hide the others.
    for (const service of ['pmm', 'inventory', 'tasks', 'nomad']) {
      expect(within(results).getByTestId(`conn-result-${service}`)).toBeInTheDocument();
    }

    expect(within(results).getByTestId('conn-status-pmm')).toHaveTextContent(/reachable/i);
    expect(within(results).getByTestId('conn-status-inventory')).toHaveTextContent(/auth failed/i);
    expect(within(results).getByTestId('conn-status-tasks')).toHaveTextContent(/timeout/i);
    expect(within(results).getByTestId('conn-status-nomad')).toHaveTextContent(/unreachable/i);

    // detail is rendered verbatim.
    expect(within(results).getByText('PMM OK')).toBeInTheDocument();
    expect(within(results).getByText('Invalid API key')).toBeInTheDocument();
  });

  it('renders version when present and omits it (no null/undefined) when absent', async () => {
    stubResults([
      { service: 'pmm', reachable: true, status: 'reachable', detail: 'OK', version: '2.44.0' },
      { service: 'nomad', reachable: true, status: 'reachable', detail: 'OK', version: null },
    ]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    const pmmRow = await screen.findByTestId('conn-result-pmm');
    expect(within(pmmRow).getByText(/2\.44\.0/)).toBeInTheDocument();

    const nomadRow = screen.getByTestId('conn-result-nomad');
    expect(nomadRow).not.toHaveTextContent(/null|undefined/i);
  });

  it('surfaces a request-level failure as an error alert with no result rows', async () => {
    server.use(
      http.post(CONN_URL, () => HttpResponse.json({ detail: 'Server error' }, { status: 500 })),
    );

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    expect(await screen.findByTestId('connectivity-error')).toBeInTheDocument();
    expect(screen.queryByTestId('connectivity-results')).not.toBeInTheDocument();
  });

  it('renders a neutral empty state when the list is empty', async () => {
    stubResults([]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    expect(await screen.findByTestId('connectivity-empty')).toBeInTheDocument();
  });

  it('renders SSL-error and generic-error chips (covers all six statuses)', async () => {
    stubResults([
      { service: 'pmm', reachable: false, status: 'ssl_error', detail: 'SSL verification failed.' },
      {
        service: 'inventory',
        reachable: false,
        status: 'error',
        detail: 'Endpoint returned an error response.',
      },
    ]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    const results = await screen.findByTestId('connectivity-results');
    expect(within(results).getByTestId('conn-status-pmm')).toHaveTextContent(/ssl error/i);
    expect(within(results).getByTestId('conn-status-inventory')).toHaveTextContent(/^error$/i);
  });

  it('falls back to the reachable flag when the status is unknown', async () => {
    // A future/unknown status must not crash the UI — chipFor() derives the chip
    // from the reachable boolean instead.
    stubResults([
      {
        service: 'pmm',
        reachable: false,
        status: 'quantum_flux' as ConnectivityStatus,
        detail: 'unclassifiable',
      },
      {
        service: 'nomad',
        reachable: true,
        status: 'quantum_flux' as ConnectivityStatus,
        detail: 'unclassifiable',
      },
    ]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    const results = await screen.findByTestId('connectivity-results');
    expect(within(results).getByTestId('conn-status-pmm')).toHaveTextContent(/not reachable/i);
    expect(within(results).getByTestId('conn-status-nomad')).toHaveTextContent(/^reachable$/i);
  });

  it('renders detail as text, never as HTML (no injection)', async () => {
    const payload = '<img src=x onerror="alert(1)">';
    stubResults([{ service: 'pmm', reachable: false, status: 'error', detail: payload }]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    const results = await screen.findByTestId('connectivity-results');
    // The payload is present verbatim as text and does not create a DOM node.
    expect(within(results).getByText(payload)).toBeInTheDocument();
    expect(within(results).queryByRole('img')).not.toBeInTheDocument();
  });

  it('ignores a second click while a check is in flight', async () => {
    const posts = vi.fn();
    server.use(
      http.post(CONN_URL, async () => {
        posts();
        // Keep the request in flight long enough for the second click under
        // a loaded suite (short delays flake when import/setup is slow).
        await delay(200);
        return HttpResponse.json([
          { service: 'pmm', reachable: true, status: 'reachable', detail: 'OK' },
        ] satisfies ConnectivityResult[]);
      }),
    );

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));
    // Disabled while pending — a second click must not fire another request.
    await waitFor(() => expect(screen.getByRole('button', { name: /testing/i })).toBeDisabled());
    // pointerEventsCheck:0 bypasses MUI's `pointer-events: none`; the button
    // handler's in-flight guard still drops the synthetic click.
    await userEvent.click(screen.getByRole('button', { name: /testing/i }), {
      pointerEventsCheck: 0,
    });

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /test connection/i })).toBeEnabled(),
    );
    expect(posts).toHaveBeenCalledTimes(1);
  });

  it('replaces stale results on a re-run', async () => {
    stubResults([
      { service: 'pmm', reachable: false, status: 'unreachable', detail: 'Connection refused' },
    ]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));
    expect(await screen.findByTestId('conn-status-pmm')).toHaveTextContent(/unreachable/i);

    // A healthy re-run must wipe the stale unreachable row, not append to it.
    stubResults([
      { service: 'pmm', reachable: true, status: 'reachable', detail: 'PMM OK' },
      { service: 'inventory', reachable: true, status: 'reachable', detail: 'Inventory OK' },
    ]);
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    await waitFor(() =>
      expect(screen.getByTestId('conn-status-pmm')).toHaveTextContent('Reachable'),
    );
    expect(screen.getByTestId('conn-status-pmm')).not.toHaveTextContent(/unreachable/i);
    expect(screen.getByTestId('conn-result-inventory')).toBeInTheDocument();
  });

  it('never renders a URL or key the response did not contain', async () => {
    stubResults([
      { service: 'pmm', reachable: true, status: 'reachable', detail: 'OK', version: '2.44.0' },
    ]);

    renderButton();
    await userEvent.click(screen.getByRole('button', { name: /test connection/i }));

    const results = await screen.findByTestId('connectivity-results');
    // The component must not reconstruct endpoint URLs/hosts client-side.
    expect(results).not.toHaveTextContent(/https?:\/\//i);
  });
});
