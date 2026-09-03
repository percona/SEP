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
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SnackbarProvider } from 'notistack';
import { ADMIN_SESSION, apiClient, AuthContext, UNAUTHENTICATED_SESSION } from '@sep/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConnectivityControl } from './ConnectivityControl';

const SERVICE_ID = 7;
const CHECK_BUTTON = /check connectivity/i;

function makeWrapper({ canMutate = true }: { canMutate?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthContext value={canMutate ? ADMIN_SESSION : UNAUTHENTICATED_SESSION}>
        <QueryClientProvider client={client}>
          <SnackbarProvider>{children}</SnackbarProvider>
        </QueryClientProvider>
      </AuthContext>
    );
  };
}

function stubPostResult(body: { success: boolean; error?: string | null }) {
  return vi
    .spyOn(apiClient, 'post')
    .mockResolvedValue({ data: { task_history_id: 1, ...body } } as never);
}

async function stubPostError(status: number, message: string) {
  const { ApiError } = await import('@sep/api');
  return vi
    .spyOn(apiClient, 'post')
    .mockRejectedValue(new ApiError({ kind: 'http', status, message }, null));
}

function renderControl(serviceType: unknown) {
  return render(<ConnectivityControl serviceId={SERVICE_ID} serviceType={serviceType} />, {
    wrapper: makeWrapper(),
  });
}

describe('ConnectivityControl', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders an enabled button for a connectable service type', async () => {
    renderControl('postgresql');
    expect(await screen.findByRole('button', { name: CHECK_BUTTON })).toBeEnabled();
  });

  it('disables the button for a service type the server cannot probe', async () => {
    renderControl('proxysql');
    expect(await screen.findByRole('button', { name: CHECK_BUTTON })).toBeDisabled();
  });

  it('explains on hover why the button is disabled', async () => {
    const user = userEvent.setup();
    renderControl('proxysql');
    // A disabled MUI button carries ``pointer-events: none``, so the hover has
    // to land on the wrapper the tooltip anchors to — as it does in a browser.
    const button = await screen.findByRole('button', { name: CHECK_BUTTON });
    await user.hover(button.parentElement!);
    await screen.findByText(/not supported for this service type/i);
  });

  it('disables the button when the record carries no service type', async () => {
    renderControl(undefined);
    expect(await screen.findByRole('button', { name: CHECK_BUTTON })).toBeDisabled();
  });

  it('POSTs to the service-scoped check endpoint', async () => {
    const user = userEvent.setup();
    const postSpy = stubPostResult({ success: true });
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        `/apps/inventory/services/${SERVICE_ID}/check-connectivity/`,
        {},
      );
    });
  });

  it('shows a spinner and disables the button while the check is in flight', async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, 'post').mockImplementation(() => new Promise(() => {}));
    renderControl('mysql');
    const button = await screen.findByRole('button', { name: CHECK_BUTTON });
    await user.click(button);
    expect(button).toBeDisabled();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('shows a success snackbar when the probe connects', async () => {
    const user = userEvent.setup();
    stubPostResult({ success: true });
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    await screen.findByText(/connectivity check passed/i);
  });

  it('shows the upstream message when the probe ran but could not connect', async () => {
    const user = userEvent.setup();
    stubPostResult({ success: false, error: 'Connection refused' });
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    await screen.findByText(/Connection refused/i);
  });

  it('falls back to a generic reason when the failed probe reports none', async () => {
    const user = userEvent.setup();
    stubPostResult({ success: false, error: null });
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    await screen.findByText(/unknown error/i);
  });

  it('shows the server detail when the check is rejected', async () => {
    const user = userEvent.setup();
    await stubPostError(400, 'Connectivity check failed for db1: missing node or port information');
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    await screen.findByText(/missing node or port information/i);
  });

  it('reports in-tree when the request never reaches the server', async () => {
    const user = userEvent.setup();
    vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('network down'));
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    expect(await screen.findByTestId('connectivity-action-error')).toHaveTextContent(
      /network down/i,
    );
  });

  it("reports a refusal in-tree with the server's own reason", async () => {
    const user = userEvent.setup();
    await stubPostError(403, "You don't have permission to perform this action");
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    expect(await screen.findByTestId('connectivity-action-error')).toHaveTextContent(
      "You don't have permission to perform this action",
    );
  });

  it('reports nothing when the probe connects', async () => {
    const user = userEvent.setup();
    stubPostResult({ success: true });
    renderControl('mysql');
    await user.click(await screen.findByRole('button', { name: CHECK_BUTTON }));
    await screen.findByText(/connectivity check passed/i);
    expect(screen.queryByTestId('connectivity-action-error')).not.toBeInTheDocument();
    expect(screen.queryByTestId('connectivity-probe-failure')).not.toBeInTheDocument();
  });

  it('re-enables the button after a failed check so it can be retried', async () => {
    const user = userEvent.setup();
    await stubPostError(502, 'Tasks API unreachable');
    renderControl('mysql');
    const button = await screen.findByRole('button', { name: CHECK_BUTTON });
    await user.click(button);
    await screen.findByText(/Tasks API unreachable/i);
    await waitFor(() => expect(button).toBeEnabled());
  });
});

describe('ConnectivityControl — write access', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the check button for a session that may mutate', () => {
    renderControl('mysql');

    expect(screen.getByRole('button', { name: CHECK_BUTTON })).toBeInTheDocument();
  });

  it('renders no check button for a non-admin', () => {
    render(<ConnectivityControl serviceId={SERVICE_ID} serviceType="mysql" />, {
      wrapper: makeWrapper({ canMutate: false }),
    });

    expect(screen.queryByRole('button', { name: CHECK_BUTTON })).not.toBeInTheDocument();
  });
});
