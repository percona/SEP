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

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { ClusterGroup } from './ClusterGroup';
import { MySQLNode } from './MySQLNode';
import { UnknownSourceNode } from './UnknownSourceNode';
import { applyDagreLayout } from './layout';
import { useCollectTopology, useTopologyResult, useTopologyStream } from './hooks';
import type { TopologyEdge, TopologyGraph, TopologyNode } from './types';

const NODE_TYPES = {
  mysql: MySQLNode,
  cluster: ClusterGroup,
  unknown_source: UnknownSourceNode,
} as unknown as NodeTypes;

/**
 * Persist the dispatched task ids in `sessionStorage` so navigating
 * away from Topology (tab switch, leaving the Inventory plugin, etc.)
 * does not clear the view: on remount we re-issue
 * `useTopologyResult` with the same ids and the TanStack Query cache
 * (gcTime=30 min) returns the graph instantly.
 *
 * Per-tab storage is intentional — different operators in different
 * browser tabs each get their own collection without interfering.
 */
const TOPOLOGY_TASK_IDS_STORAGE_KEY = 'sep.inventory.topology.taskIds';
const TOPOLOGY_AUTO_COLLECT_STORAGE_KEY = 'inventory-topology-auto-collect-fired';

function readPersistedTaskIds(): number[] | null {
  if (typeof sessionStorage === 'undefined') {
    return null;
  }
  try {
    const raw = sessionStorage.getItem(TOPOLOGY_TASK_IDS_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return null;
    }
    const ids = parsed.filter((x): x is number => typeof x === 'number' && Number.isFinite(x));
    return ids.length > 0 ? ids : null;
  } catch {
    return null;
  }
}

function persistTaskIds(ids: number[] | null): void {
  if (typeof sessionStorage === 'undefined') {
    return;
  }
  try {
    if (ids === null || ids.length === 0) {
      sessionStorage.removeItem(TOPOLOGY_TASK_IDS_STORAGE_KEY);
    } else {
      sessionStorage.setItem(TOPOLOGY_TASK_IDS_STORAGE_KEY, JSON.stringify(ids));
    }
  } catch {
    // sessionStorage can throw under quota or privacy-mode limits;
    // failing silently keeps the in-memory state authoritative.
  }
}

function toFlowNodes(graph: TopologyGraph | null): Node[] {
  if (!graph) {
    return [];
  }
  return graph.nodes.map(
    (node: TopologyNode): Node => ({
      id: node.id,
      type: node.type,
      position: { x: 0, y: 0 },
      data: node.data as unknown as Record<string, unknown>,
    }),
  );
}

function toFlowEdges(graph: TopologyGraph | null): Edge[] {
  if (!graph) {
    return [];
  }
  return graph.edges.map((edge: TopologyEdge): Edge => {
    const isReplication = edge.type === 'replication';
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: isReplication ? 'smoothstep' : 'straight',
      animated: isReplication,
      label: edge.type === 'dual_primary' ? 'dual primary' : undefined,
      style: {
        stroke:
          edge.type === 'dual_primary'
            ? '#d32f2f'
            : (edge.data as Record<string, unknown> | undefined)?.['status'] === 'err'
              ? '#ed6c02'
              : '#1976d2',
        strokeWidth: edge.type === 'dual_primary' ? 2 : 1.5,
      },
      markerEnd:
        edge.type === 'dual_primary'
          ? undefined
          : { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      data: edge.data as unknown as Record<string, unknown> | undefined,
    };
  });
}

function TopologyCanvas({ graph }: { graph: TopologyGraph | null }) {
  const layoutNodes = useMemo(() => {
    const nodes = toFlowNodes(graph);
    const edges = toFlowEdges(graph);
    return applyDagreLayout(nodes, edges);
  }, [graph]);
  const edges = useMemo(() => toFlowEdges(graph), [graph]);

  if (!graph || graph.nodes.length === 0) {
    return (
      <Box
        sx={{
          height: 500,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: 1,
          borderStyle: 'dashed',
          borderColor: 'divider',
          borderRadius: 2,
        }}
      >
        <Typography color="text.secondary">
          No topology data yet. Click <strong>Refresh</strong> to collect.
        </Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        height: 'calc(100vh - 320px)',
        minHeight: 480,
        border: 1,
        borderColor: 'divider',
        borderRadius: 2,
      }}
    >
      <ReactFlowProvider>
        <ReactFlow
          nodes={layoutNodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} />
          <Controls />
        </ReactFlow>
      </ReactFlowProvider>
    </Box>
  );
}

/**
 * Inventory Topology view — dispatches a live MySQL topology collection
 * and renders the resulting React Flow graph. Caches the latest graph in
 * TanStack Query (long staleTime, manual refresh) so navigating away and
 * back is instant.
 */
export function InventoryTopology() {
  const [taskIds, setTaskIdsState] = useState<number[] | null>(readPersistedTaskIds);
  const setTaskIds = useCallback((ids: number[] | null) => {
    setTaskIdsState(ids);
    persistTaskIds(ids);
  }, []);
  const collect = useCollectTopology();
  const result = useTopologyResult(taskIds);
  const stream = useTopologyStream(taskIds, { enabled: !!taskIds });
  const [autoCollectHandled, setAutoCollectHandled] = useState<boolean>(() => {
    if (typeof window === 'undefined') {
      return false;
    }

    return window.sessionStorage.getItem(TOPOLOGY_AUTO_COLLECT_STORAGE_KEY) === 'true';
  });

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    window.sessionStorage.setItem(
      TOPOLOGY_AUTO_COLLECT_STORAGE_KEY,
      autoCollectHandled ? 'true' : 'false',
    );
  }, [autoCollectHandled]);

  const markAutoCollectHandled = useCallback(() => {
    setAutoCollectHandled(true);
  }, []);

  const handleRefresh = useCallback(async () => {
    markAutoCollectHandled();
    const response = await collect.mutateAsync(undefined);
    setTaskIds(response.task_history_ids);
  }, [collect, markAutoCollectHandled, setTaskIds]);

  useEffect(() => {
    if (taskIds !== null) {
      markAutoCollectHandled();
    }
  }, [taskIds, markAutoCollectHandled]);

  // First-visit auto-collect: when a fresh Topology page has nothing
  // persisted, kick off a collection automatically so the user sees a
  // loading spinner rather than the empty "Click Collect" placeholder.
  // Idempotent across remounts and re-renders because the "already
  // handled" state is persisted for the browser session.
  useEffect(() => {
    if (taskIds === null && !collect.isPending && !collect.error && !autoCollectHandled) {
      void handleRefresh();
    }
  }, [taskIds, collect.isPending, collect.error, autoCollectHandled, handleRefresh]);

  const isCollecting = collect.isPending || result.data?.status === 'running';
  const graph = result.data?.graph ?? null;
  const summary = graph?.summary;

  // The graph is rendered from `useTopologyResult` polling, not from
  // the SSE stream. When polling has already delivered a successful
  // graph, surfacing a "stream connection lost" alert next to the
  // working graph is a UX bug (the stream is just a progress nicety,
  // its failure isn't user-actionable).
  const pollingDeliveredData = result.data?.status === 'ok' && (graph?.nodes.length ?? 0) > 0;
  const showStreamError = !!stream.error && !stream.isStreaming && !pollingDeliveredData;

  return (
    <Stack spacing={2} sx={{ mt: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between">
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="h6">MySQL Topology</Typography>
          {summary ? (
            <>
              <Chip size="small" label={`${summary.host_count} host(s)`} />
              {summary.cluster_count > 0 ? (
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${summary.cluster_count} cluster(s)`}
                />
              ) : null}
              {summary.error_count > 0 ? (
                <Chip size="small" color="error" label={`${summary.error_count} unreachable`} />
              ) : null}
              {stream.isStreaming ? (
                <Chip
                  size="small"
                  variant="outlined"
                  label={`streaming · ${stream.hostsCompleted}/${summary.host_count}`}
                />
              ) : null}
            </>
          ) : null}
        </Stack>
        <Button
          variant="contained"
          onClick={handleRefresh}
          disabled={collect.isPending}
          data-testid="topology-refresh-button"
        >
          {taskIds ? 'Refresh' : 'Collect'}
        </Button>
      </Stack>

      {collect.error ? <Alert severity="error">{collect.error.message}</Alert> : null}
      {result.error ? (
        <Alert severity="error">Failed to load result: {result.error.message}</Alert>
      ) : null}
      {showStreamError ? (
        <Alert
          severity="warning"
          data-testid="topology-stream-error"
          action={
            <Button
              color="inherit"
              size="small"
              onClick={stream.dismissError}
              data-testid="topology-stream-error-dismiss"
            >
              Dismiss
            </Button>
          }
        >
          {stream.error!.message}
        </Alert>
      ) : null}

      {isCollecting ? <LinearProgress /> : null}

      <TopologyCanvas graph={graph} />
    </Stack>
  );
}
