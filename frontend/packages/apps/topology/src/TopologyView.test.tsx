/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { apiClient, AuthContext, UNAUTHENTICATED_SESSION } from '@sep/api';
import { TOPOLOGY_TASK_IDS_STORAGE_KEY, TopologyView } from './TopologyView';
import type { TopologyGraph } from './types';

const SAMPLE_GRAPH: TopologyGraph = {
  nodes: [
    {
      id: 'mysql:host-a:3306',
      type: 'mysql',
      data: {
        host_entry: 'host-a:3306',
        status: 'ok',
        address: 'host-a',
        port: 3306,
        server: { read_only: 'RW', version: '8.0.42' },
        replication: { source_host: null },
      },
    },
    {
      id: 'mysql:host-b:3306',
      type: 'mysql',
      data: {
        host_entry: 'host-b:3306',
        status: 'ok',
        address: 'host-b',
        port: 3306,
        server: { read_only: 'RO', version: '8.0.42' },
        replication: {
          source_host: 'host-a',
          source_port: 3306,
          repl_status: 'ok',
        },
      },
    },
  ],
  edges: [
    {
      id: 'repl:mysql:host-a:3306->mysql:host-b:3306',
      source: 'mysql:host-a:3306',
      target: 'mysql:host-b:3306',
      type: 'replication',
      data: { status: 'ok' },
    },
  ],
  summary: {
    host_count: 2,
    ok_count: 2,
    error_count: 0,
    cluster_count: 0,
    edge_count: 1,
  },
};

/** Session state for a signed-in administrator (the only session that may mutate). */
const ADMIN_SESSION = {
  ...UNAUTHENTICATED_SESSION,
  isAuthenticated: true,
  isAdmin: true,
  ready: true,
};

function renderTopology({ canMutate = true }: { canMutate?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AuthContext value={canMutate ? ADMIN_SESSION : UNAUTHENTICATED_SESSION}>
      <QueryClientProvider client={client}>
        <TopologyView />
      </QueryClientProvider>
    </AuthContext>,
  );
}

describe('TopologyView', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it('does not auto-collect on mount; shows the empty placeholder', async () => {
    const post = vi.spyOn(apiClient, 'post');
    vi.spyOn(apiClient, 'get');

    renderTopology();

    expect(await screen.findByText(/No topology data yet/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByTestId('topology-refresh-button')).toHaveTextContent('Collect');
  });

  it('rehydrates instantly from persisted task ids without dispatching a collect', async () => {
    sessionStorage.setItem(TOPOLOGY_TASK_IDS_STORAGE_KEY, '[42]');
    const post = vi.spyOn(apiClient, 'post');
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'ok', graph: SAMPLE_GRAPH },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();

    await screen.findByTestId('mysql-node-host-a:3306');
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByTestId('topology-refresh-button')).toHaveTextContent('Refresh');
  });

  it('dispatches a collect on click, polls /result, and renders nodes once ready', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [11],
        targets: ['exec-a'],
        host_count: 2,
        shard_count: 1,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'ok', graph: SAMPLE_GRAPH },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();

    fireEvent.click(screen.getByTestId('topology-refresh-button'));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/apps/topology/collect', {});
    });
    await waitFor(() => {
      expect(sessionStorage.getItem(TOPOLOGY_TASK_IDS_STORAGE_KEY)).toBe('[11]');
    });

    await screen.findByTestId('mysql-node-host-a:3306');
    expect(screen.getByTestId('mysql-node-host-b:3306')).toBeInTheDocument();
    expect(screen.getByText('2 host(s)')).toBeInTheDocument();
  });

  it('shows an error when the collect dispatch fails', async () => {
    vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('collect failed'));

    renderTopology();

    fireEvent.click(screen.getByTestId('topology-refresh-button'));

    await screen.findByText('collect failed');
    expect(sessionStorage.getItem(TOPOLOGY_TASK_IDS_STORAGE_KEY)).toBeNull();
  });
});

describe('TopologyView — write access', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it('renders the collect button for a session that may mutate', async () => {
    vi.spyOn(apiClient, 'get');

    renderTopology();

    expect(await screen.findByTestId('topology-refresh-button')).toBeInTheDocument();
  });

  it('renders no collect button for a non-admin, keeping the graph readable', async () => {
    sessionStorage.setItem(TOPOLOGY_TASK_IDS_STORAGE_KEY, '[42]');
    const post = vi.spyOn(apiClient, 'post');
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'ok', graph: SAMPLE_GRAPH },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology({ canMutate: false });

    await screen.findByTestId('mysql-node-host-a:3306');
    expect(screen.queryByTestId('topology-refresh-button')).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });
});
