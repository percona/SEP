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

/**
 * Backend topology shapes shared between the API hooks, layout helpers,
 * and the React Flow node/edge components. Mirrors `app/sep/apps/topology/
 * topology.py::build_topology_graph` — keep keys in sync.
 */

export type MySQLNodeStatus = 'ok' | 'error';

export interface MySQLServerInfo {
  server_hash?: string | null;
  server_id?: number | null;
  server_uuid?: string | null;
  port?: number | null;
  hostname?: string | null;
  version?: string | null;
  log_bin?: 'ON' | 'OFF' | null;
  read_only?: 'RW' | 'RO' | 'SR' | null;
}

export interface MySQLReplicationInfo {
  source_host?: string | null;
  source_port?: number | null;
  source_server_id?: number | null;
  io_running?: string | null;
  sql_running?: string | null;
  seconds_behind?: number | null;
  repl_status?: 'ok' | 'err' | null;
  repl_filter?: 'yes' | 'none' | null;
  auto_position?: number | null;
}

export interface MySQLClusterInfo {
  cluster_name: string;
  cluster_size?: string | null;
  cluster_status?: string | null;
  local_state_comment?: string | null;
}

export interface MySQLNodeData {
  host_entry: string;
  status: MySQLNodeStatus;
  address?: string | null;
  port?: number | null;
  error?: string | null;
  server?: MySQLServerInfo;
  replication?: MySQLReplicationInfo;
  cluster?: MySQLClusterInfo | null;
  gtid_mode?: string | null;
}

export interface ClusterNodeData {
  cluster_name: string;
  size?: string | null;
  status?: string | null;
  members: string[];
}

export interface UnknownSourceNodeData {
  address?: string | null;
  port?: number | null;
  reason?: string | null;
}

export type TopologyNode =
  | { id: string; type: 'mysql'; data: MySQLNodeData }
  | { id: string; type: 'cluster'; data: ClusterNodeData }
  | { id: string; type: 'unknown_source'; data: UnknownSourceNodeData };

export interface ReplicationEdgeData {
  status?: 'ok' | 'err' | null;
  io_running?: string | null;
  sql_running?: string | null;
  seconds_behind?: number | null;
  auto_position?: number | null;
  filter?: string | null;
  gtid_mode?: string | null;
}

export type TopologyEdge =
  | {
      id: string;
      source: string;
      target: string;
      type: 'replication';
      data?: ReplicationEdgeData;
    }
  | {
      id: string;
      source: string;
      target: string;
      type: 'dual_primary';
      data?: { [key: string]: unknown };
    };

export interface TopologyGraphSummary {
  host_count: number;
  ok_count: number;
  error_count: number;
  cluster_count: number;
  edge_count: number;
}

export interface TopologyGraph {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  summary: TopologyGraphSummary;
}

/** API responses */

export interface TopologyCollectResponse {
  task_history_ids: number[];
  targets: string[];
  host_count: number;
  shard_count: number;
}

export interface TopologyResultResponse {
  status: 'running' | 'ok' | 'failed';
  graph: TopologyGraph | null;
  pending_task_ids?: number[];
  failed_task_ids?: number[];
}
