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
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError, apiClient } from '@sep/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SystemFactsPanel } from './SystemFactsPanel';

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('SystemFactsPanel', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders the host facts when a node observation is present', async () => {
    // Host observation shape: os_version / installed_packages / config, no
    // db_engine_version.
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        os_version: 'Ubuntu 22.04',
        installed_packages: { openssl: '3.0.2' },
        config: { max_connections: 100 },
        observed_at: '2026-06-01T12:00:00Z',
      },
    });

    render(<SystemFactsPanel entity="nodes" id={3} />, { wrapper: makeWrapper() });

    expect(await screen.findByText('Ubuntu 22.04')).toBeInTheDocument();
    // JSON blobs are pretty-printed; assert a representative fragment.
    expect(screen.getByText(/openssl/)).toBeInTheDocument();
    expect(screen.getByText(/max_connections/)).toBeInTheDocument();
    expect(screen.getByText(/Observed at/)).toBeInTheDocument();
    // The node panel must not surface the service-only field.
    expect(screen.queryByText('Database engine version')).not.toBeInTheDocument();
    // The empty-state copy must not appear when facts are present.
    expect(screen.queryByText(/No system facts collected yet/)).not.toBeInTheDocument();
  });

  it('renders the service facts when a service observation is present', async () => {
    // Service observation shape: db_engine_version only.
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        db_engine_version: '8.0.36',
        observed_at: '2026-06-01T12:00:00Z',
      },
    });

    render(<SystemFactsPanel entity="services" id={9} />, { wrapper: makeWrapper() });

    expect(await screen.findByText('8.0.36')).toBeInTheDocument();
    expect(screen.getByText(/Observed at/)).toBeInTheDocument();
    // The service panel must not surface host-only fields.
    expect(screen.queryByText('OS version')).not.toBeInTheDocument();
    expect(screen.queryByText('Installed packages')).not.toBeInTheDocument();
    expect(screen.queryByText('Config')).not.toBeInTheDocument();
    expect(screen.queryByText(/No system facts collected yet/)).not.toBeInTheDocument();
  });

  it('renders the empty state when the upstream returns 404', async () => {
    vi.spyOn(apiClient, 'get').mockRejectedValue(
      new ApiError({ kind: 'http', status: 404, message: 'Not found' }, null),
    );

    render(<SystemFactsPanel entity="services" id={9} />, { wrapper: makeWrapper() });

    expect(await screen.findByText('No system facts collected yet')).toBeInTheDocument();
    expect(screen.queryByText('Could not load system facts.')).not.toBeInTheDocument();
  });

  it('renders an error message on a non-404 failure', async () => {
    vi.spyOn(apiClient, 'get').mockRejectedValue(
      new ApiError({ kind: 'http', status: 500, message: 'Server error' }, null),
    );

    render(<SystemFactsPanel entity="nodes" id={3} />, { wrapper: makeWrapper() });

    expect(await screen.findByText('Could not load system facts.')).toBeInTheDocument();
    expect(screen.queryByText('No system facts collected yet')).not.toBeInTheDocument();
  });
});
