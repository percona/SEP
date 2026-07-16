# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define Pydantic models for the Topology plugin's collect/result API."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

MAX_TOPOLOGY_SHARDS = 8


class TopologyCollectWrite(BaseModel):
    """Describe the request body for ``POST /collect``.

    :param shards: Number of executor hosts to dispatch in parallel. Hosts
        are split round-robin across the chosen executors. Capped at
        :data:`MAX_TOPOLOGY_SHARDS`.
    :type shards: int
    :param executor_host: Optional explicit executor. Must be used with
        ``shards=1`` because it selects a single-shard run.
    :type executor_host: str | None
    :param connect_timeout: Per-host MySQL TCP connect timeout (seconds).
    :type connect_timeout: int
    :param read_timeout: Per-host MySQL read/write timeout (seconds).
    :type read_timeout: int
    """

    shards: int = Field(default=1, ge=1, le=MAX_TOPOLOGY_SHARDS)
    executor_host: str | None = None
    connect_timeout: int = Field(default=5, ge=1, le=60)
    read_timeout: int = Field(default=10, ge=1, le=120)

    @model_validator(mode="after")
    def _reject_executor_with_multiple_shards(self) -> Self:
        if self.executor_host and self.shards != 1:
            raise ValueError("executor_host requires shards=1")
        return self


class TopologyCollectResponse(BaseModel):
    """Represent the response body for ``POST /collect``.

    ``task_history_ids`` lists the dispatched ``run-python`` tasks the
    frontend then polls (``/result``) to assemble the topology graph.
    ``targets`` echoes the executor hosts the work was sharded across so
    the UI can surface where the collection ran.

    :param task_history_ids: Created task history ids, one per shard.
    :type task_history_ids: list[int]
    :param targets: Executor hosts selected for topology collection.
    :type targets: list[str]
    :param host_count: Number of MySQL hosts included in the collection.
    :type host_count: int
    :param shard_count: Number of dispatched topology shards.
    :type shard_count: int
    """

    task_history_ids: list[int]
    targets: list[str]
    host_count: int
    shard_count: int


class MySQLServerInfo(BaseModel):
    """Represent MySQL server identity/mode collected per host."""

    server_hash: str | None = None
    server_id: int | None = None
    server_uuid: str | None = None
    port: int | None = None
    hostname: str | None = None
    version: str | None = None
    log_bin: Literal["ON", "OFF"] | None = None
    read_only: Literal["RW", "RO", "SR"] | None = None


class MySQLReplicationInfo(BaseModel):
    """Represent replication source/state for a replica host (``source_uuid`` stripped)."""

    source_host: str | None = None
    source_port: int | None = None
    source_server_id: int | None = None
    io_running: str | None = None
    sql_running: str | None = None
    seconds_behind: int | None = None
    repl_status: Literal["ok", "err"] | None = None
    repl_filter: Literal["yes", "none"] | None = None
    auto_position: int | None = None


class MySQLClusterInfo(BaseModel):
    """Represent Percona XtraDB Cluster (wsrep) metadata for a host."""

    cluster_name: str
    cluster_size: str | None = None
    cluster_status: str | None = None
    local_state_comment: str | None = None


class MySQLNodeData(BaseModel):
    """Represent the React-Flow ``data`` payload for a MySQL node."""

    host_entry: str
    status: Literal["ok", "error"]
    address: str | None = None
    port: int | None = None
    error: str | None = None
    server: MySQLServerInfo | None = None
    replication: MySQLReplicationInfo | None = None
    cluster: MySQLClusterInfo | None = None
    gtid_mode: str | None = None


class ClusterNodeData(BaseModel):
    """Represent the React-Flow ``data`` payload for a synthetic PXC cluster node."""

    cluster_name: str
    size: str | None = None
    status: str | None = None
    members: list[str] = Field(default_factory=list)


class UnknownSourceNodeData(BaseModel):
    """Represent the React-Flow ``data`` payload for a replication source not in inventory."""

    address: str | None = None
    port: int | None = None
    reason: str | None = None


class MySQLNode(BaseModel):
    """Represent a MySQL server node in the topology graph."""

    id: str
    type: Literal["mysql"]
    data: MySQLNodeData


class ClusterNode(BaseModel):
    """Represent a synthetic cluster-group node in the topology graph."""

    id: str
    type: Literal["cluster"]
    data: ClusterNodeData


class UnknownSourceNode(BaseModel):
    """Represent a synthetic node for a replication source absent from inventory."""

    id: str
    type: Literal["unknown_source"]
    data: UnknownSourceNodeData


TopologyNode = Annotated[
    MySQLNode | ClusterNode | UnknownSourceNode,
    Field(discriminator="type"),
]


class ReplicationEdgeData(BaseModel):
    """Represent the React-Flow ``data`` payload for a replication edge."""

    status: Literal["ok", "err"] | None = None
    io_running: str | None = None
    sql_running: str | None = None
    seconds_behind: int | None = None
    auto_position: int | None = None
    filter: str | None = None
    gtid_mode: str | None = None


class ReplicationEdge(BaseModel):
    """Represent a primary -> replica replication edge."""

    id: str
    source: str
    target: str
    type: Literal["replication"]
    data: ReplicationEdgeData | None = None


class DualPrimaryEdge(BaseModel):
    """Represent a dual-primary (mutually replicating) edge."""

    id: str
    source: str
    target: str
    type: Literal["dual_primary"]
    data: dict[str, Any] = Field(default_factory=dict)


TopologyEdge = Annotated[
    ReplicationEdge | DualPrimaryEdge,
    Field(discriminator="type"),
]


class TopologyGraphSummary(BaseModel):
    """Aggregate counts for the topology graph."""

    host_count: int
    ok_count: int
    error_count: int
    cluster_count: int
    edge_count: int


class TopologyGraph(BaseModel):
    """Represent the merged React-Flow ``{nodes, edges, summary}`` graph."""

    nodes: list[TopologyNode] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)
    summary: TopologyGraphSummary


class TopologyResultResponse(BaseModel):
    """Represent the response body for ``GET /result``.

    ``status`` is ``running`` while any of the underlying tasks is
    still pending, ``ok`` once every task has finished, and ``failed``
    when at least one task failed and produced no usable output.
    ``graph`` is the merged React-Flow graph; ``pending_task_ids``
    lists the still-running tasks for the UI's progress chip, and
    ``failed_task_ids`` lets the UI warn when only some shards failed.

    :param status: Aggregate topology collection status.
    :type status: Literal["running", "ok", "failed"]
    :param graph: Merged React-Flow graph when collection output is ready.
    :type graph: TopologyGraph | None
    :param pending_task_ids: Task ids still pending or running.
    :type pending_task_ids: list[int]
    :param failed_task_ids: Terminal task ids that did not finish successfully.
    :type failed_task_ids: list[int]
    """

    status: Literal["running", "ok", "failed"]
    graph: TopologyGraph | None = None
    pending_task_ids: list[int] = Field(default_factory=list)
    failed_task_ids: list[int] = Field(default_factory=list)
