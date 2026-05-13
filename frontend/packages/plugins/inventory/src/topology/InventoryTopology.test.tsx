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
import { apiClient } from '@sep/api';
import { InventoryTopology } from './InventoryTopology';
import type { TopologyGraph } from './types';

class FakeEventSource {
  url: string;
  withCredentials: boolean;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
  private listeners = new Map<string, Set<(ev: MessageEvent) => unknown>>();
  static last: FakeEventSource | undefined;
  closed = false;

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = !!init?.withCredentials;
    FakeEventSource.last = this;
  }

  addEventListener(name: string, handler: (ev: MessageEvent) => unknown) {
    let bucket = this.listeners.get(name);
    if (!bucket) {
      bucket = new Set();
      this.listeners.set(name, bucket);
    }
    bucket.add(handler);
  }

  removeEventListener(name: string, handler: (ev: MessageEvent) => unknown) {
    this.listeners.get(name)?.delete(handler);
  }

  emit(name: string, data: unknown) {
    const ev = { data: JSON.stringify(data) } as MessageEvent;
    for (const handler of this.listeners.get(name) ?? []) {
      handler(ev);
    }
  }

  fireError() {
    this.onerror?.call(this as unknown as EventSource, new Event('error'));
  }

  close() {
    this.closed = true;
  }
}

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

function renderTopology() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InventoryTopology />
    </QueryClientProvider>,
  );
}

const TOPOLOGY_TASK_IDS_STORAGE_KEY = 'sep.inventory.topology.taskIds';

describe('InventoryTopology', () => {
  beforeEach(() => {
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    sessionStorage.clear();
    FakeEventSource.last = undefined;
  });

  it('auto-collects on first mount when nothing is persisted', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [301],
        targets: ['exec-a'],
        host_count: 1,
        shard_count: 1,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'running', graph: null, pending_task_ids: [301] },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();

    // The user lands on a loading state, not the empty placeholder.
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/plugins/inventory/topology/collect', {});
    });
    await waitFor(() => {
      expect(sessionStorage.getItem(TOPOLOGY_TASK_IDS_STORAGE_KEY)).toBe('[301]');
    });
  });

  it('skips auto-collect and rehydrates instantly from persisted task ids', async () => {
    sessionStorage.setItem(TOPOLOGY_TASK_IDS_STORAGE_KEY, '[42]');
    const post = vi.spyOn(apiClient, 'post');
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'ok', graph: SAMPLE_GRAPH },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();

    // Graph from cache/poll appears without a /collect dispatch.
    await screen.findByTestId('mysql-node-host-a:3306');
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByTestId('topology-refresh-button')).toHaveTextContent('Refresh');
  });

  it('dispatches a collect, polls /result, and renders nodes once ready', async () => {
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

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/plugins/inventory/topology/collect', {});
    });

    await screen.findByTestId('mysql-node-host-a:3306');
    expect(screen.getByTestId('mysql-node-host-b:3306')).toBeInTheDocument();
    expect(screen.getByText('2 host(s)')).toBeInTheDocument();
  });

  it('opens an SSE connection scoped to the dispatched task ids', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [42, 43],
        targets: ['exec-a', 'exec-b'],
        host_count: 4,
        shard_count: 2,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'running', graph: null, pending_task_ids: [42, 43] },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();

    await waitFor(() => {
      expect(FakeEventSource.last?.url).toContain('/api/plugins/inventory/topology/stream');
      expect(FakeEventSource.last?.url).toContain('ids=42%2C43');
    });
  });

  it('does not surface a stream error after a normal complete event', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [55],
        targets: ['exec-a'],
        host_count: 1,
        shard_count: 1,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'ok', graph: SAMPLE_GRAPH },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();
    await waitFor(() => expect(FakeEventSource.last).toBeDefined());

    const source = FakeEventSource.last!;
    source.emit('complete', { task_history_ids: [55] });
    source.fireError();

    await new Promise((r) => setTimeout(r, 5));

    expect(screen.queryByTestId('topology-stream-error')).not.toBeInTheDocument();
    expect(source.closed).toBe(true);
  });

  it('surfaces an error message that includes task ids and elapsed time on a real drop', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [77, 78],
        targets: ['exec-a', 'exec-b'],
        host_count: 2,
        shard_count: 2,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'running', graph: null, pending_task_ids: [77, 78] },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();
    await waitFor(() => expect(FakeEventSource.last).toBeDefined());

    FakeEventSource.last!.emit('host_done', {
      task_history_id: 77,
      event: 'host_done',
      host: 'host-a:3306',
      data: {},
    });
    FakeEventSource.last!.fireError();

    const alert = await screen.findByTestId('topology-stream-error');
    expect(alert).toHaveTextContent(/Topology stream connection lost for task\(s\)\s*77,78/);
    expect(alert).toHaveTextContent(/1 event\(s\)/);
    expect(alert).toHaveTextContent(/elapsed/);
  });

  it('suppresses the stream alert when polling already delivered the graph', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [161],
        targets: ['exec-a'],
        host_count: 1,
        shard_count: 1,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'ok', graph: SAMPLE_GRAPH },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();
    await waitFor(() => expect(FakeEventSource.last).toBeDefined());

    // SSE drops immediately, before any event arrives — exactly the
    // "0 events, 0.0s elapsed" symptom from a dev-server proxy quirk
    // or an SSE-incompatible auth path. Polling has the data, so no
    // stream alert should ever appear.
    FakeEventSource.last!.fireError();

    await screen.findByTestId('mysql-node-host-a:3306');
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('topology-stream-error')).not.toBeInTheDocument();
  });

  it('dismiss button removes the alert', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        task_history_ids: [201],
        targets: ['exec-a'],
        host_count: 1,
        shard_count: 1,
      },
    } as Awaited<ReturnType<typeof apiClient.post>>);
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { status: 'running', graph: null, pending_task_ids: [201] },
    } as Awaited<ReturnType<typeof apiClient.get>>);

    renderTopology();
    await waitFor(() => expect(FakeEventSource.last).toBeDefined());
    FakeEventSource.last!.fireError();

    await screen.findByTestId('topology-stream-error');
    fireEvent.click(screen.getByTestId('topology-stream-error-dismiss'));

    await waitFor(() => {
      expect(screen.queryByTestId('topology-stream-error')).not.toBeInTheDocument();
    });
  });
});
