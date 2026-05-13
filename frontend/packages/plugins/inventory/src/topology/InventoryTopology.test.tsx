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
import { apiClient, setOnUnauthorized, setTokenProvider } from '@sep/api';
import { InventoryTopology } from './InventoryTopology';
import type { TopologyGraph } from './types';

const encoder = new TextEncoder();

interface MockStreamHandle {
  url: string;
  requestHeaders: Record<string, string>;
  signal: AbortSignal | undefined;
  pushNamed: (event: string, data: unknown) => void;
  errorStream: (reason?: unknown) => void;
}

function flushPromises(): Promise<void> {
  return new Promise((resolve) => {
    queueMicrotask(() => queueMicrotask(() => queueMicrotask(() => queueMicrotask(resolve))));
  });
}

function createMockStreamFetch() {
  const pending: MockStreamHandle[] = [];
  const fetchSpy = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;

    let ctrl!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        ctrl = c;
      },
    });

    const rawHeaders = init?.headers;
    let requestHeaders: Record<string, string> = {};
    if (rawHeaders instanceof Headers) {
      requestHeaders = Object.fromEntries(rawHeaders.entries());
    } else if (Array.isArray(rawHeaders)) {
      requestHeaders = Object.fromEntries(rawHeaders);
    } else if (rawHeaders) {
      requestHeaders = rawHeaders as Record<string, string>;
    }

    pending.push({
      url,
      requestHeaders,
      signal: init?.signal ?? undefined,
      pushNamed(event, data) {
        ctrl.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      },
      errorStream(reason) {
        ctrl.error(reason);
      },
    });

    return Promise.resolve(
      new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );
  });

  return { pending, fetchSpy };
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
  let streamFetch: ReturnType<typeof createMockStreamFetch>;

  beforeEach(() => {
    streamFetch = createMockStreamFetch();
    vi.stubGlobal('fetch', streamFetch.fetchSpy);
    setTokenProvider(() => 'test-access-token');
    setOnUnauthorized(() => {});
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    setTokenProvider(() => null);
    setOnUnauthorized(() => {});
    sessionStorage.clear();
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
      expect(streamFetch.pending[0]?.url).toContain('/api/plugins/inventory/topology/stream');
      expect(streamFetch.pending[0]?.url).toContain('ids=42%2C43');
      expect(streamFetch.pending[0]?.requestHeaders.authorization).toBe('Bearer test-access-token');
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
    await waitFor(() => expect(streamFetch.pending[0]).toBeDefined());

    const source = streamFetch.pending[0]!;
    source.pushNamed('complete', { task_history_ids: [55] });
    await flushPromises();

    expect(screen.queryByTestId('topology-stream-error')).not.toBeInTheDocument();
    expect(source.signal?.aborted).toBe(true);
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
    await waitFor(() => expect(streamFetch.pending[0]).toBeDefined());

    streamFetch.pending[0]!.pushNamed('host_done', {
      task_history_id: 77,
      event: 'host_done',
      host: 'host-a:3306',
      data: {},
    });
    streamFetch.pending[0]!.errorStream(new Error('boom'));

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
    await waitFor(() => expect(streamFetch.pending[0]).toBeDefined());

    // SSE drops immediately, before any event arrives — exactly the
    // "0 events, 0.0s elapsed" symptom from a dev-server proxy quirk
    // or an SSE-incompatible auth path. Polling has the data, so no
    // stream alert should ever appear.
    streamFetch.pending[0]!.errorStream(new Error('boom'));

    await screen.findByTestId('mysql-node-host-a:3306');
    await flushPromises();
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
    await waitFor(() => expect(streamFetch.pending[0]).toBeDefined());
    streamFetch.pending[0]!.errorStream(new Error('boom'));

    await screen.findByTestId('topology-stream-error');
    fireEvent.click(screen.getByTestId('topology-stream-error-dismiss'));

    await waitFor(() => {
      expect(screen.queryByTestId('topology-stream-error')).not.toBeInTheDocument();
    });
  });
});
